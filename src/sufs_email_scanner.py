"""
Scans Gmail for SUFS status emails (approval and payment notifications)
and matches them to tracking sheet rows via the reimbursement ID in column K.

Email formats:
  Approved — from: no-reply@sufs.org, subject: "Reimbursement request approved"
             body: Student's Name / Reimbursement ID / amount / category
  Paid     — from: no-reply@sufs.org, subject: "<PROGRAM> submitted a payment to you"
             body: "Payment message: Invoices 33010312-1,33010312-2"
"""

import os
import re
from datetime import datetime

# SUFS sends from two address variants — approvals/on-hold use the hyphenated
# "no-reply@sufs.org", while payment notifications come from the un-hyphenated
# "noreply@sufs.org". Match both so direct-to-Gmail payment emails are caught
# (these used to be forwarded via the Arizona account, masking the mismatch).
SUFS_SENDER = "(no-reply@sufs.org OR noreply@sufs.org)"
GMAIL_TOKEN_FILE = "token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


# ---------------------------------------------------------------------------
# Gmail helpers (mirrors amazon_scanner.py pattern)
# ---------------------------------------------------------------------------

def _get_gmail_service():
    from pathlib import Path
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_path = os.environ.get("GMAIL_TOKEN_FILE", GMAIL_TOKEN_FILE)
    if not Path(token_path).exists():
        raise RuntimeError(
            "Gmail not authorized. Run authorize_gmail.py first to create token.json."
        )
    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        Path(token_path).write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _decode_body(msg) -> str:
    """Extract plain or HTML text from a Gmail message payload."""
    import base64
    import re as _re

    def _extract(payload) -> str:
        mime = payload.get("mimeType", "")
        data = payload.get("body", {}).get("data", "")
        if mime == "text/plain" and data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        if mime == "text/html" and data:
            html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            return _re.sub(r"<[^>]+>", " ", html)
        for part in payload.get("parts", []):
            result = _extract(part)
            if result:
                return result
        return ""

    return _extract(msg.get("payload", {}))


def _list_messages(service, query: str) -> list[dict]:
    """Return all message stubs matching a Gmail query."""
    messages = []
    page_token = None
    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.users().messages().list(**kwargs).execute()
        messages.extend(resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return messages


def _email_date(msg) -> str:
    """Return M/D/YYYY date from message headers."""
    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    raw = headers.get("Date", "")
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).strftime("%m/%d/%Y")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Approved email scanner
# ---------------------------------------------------------------------------

def scan_approved_emails(after_date: str = None) -> list[dict]:
    """
    Scan for SUFS approval emails.
    after_date: optional YYYY/MM/DD string to limit search.
    Returns list of dicts: {reimbursement_id, student, amount, category, date, email_id}
    """
    svc = _get_gmail_service()
    query = f'from:{SUFS_SENDER} subject:"Reimbursement request approved"'
    if after_date:
        query += f" after:{after_date}"

    results = []
    for stub in _list_messages(svc, query):
        msg = svc.users().messages().get(
            userId="me", id=stub["id"], format="full"
        ).execute()
        body = _decode_body(msg)

        reimb   = re.search(r"Reimbursement ID:\s*(\d+)", body)
        student = re.search(r"Student['’]s Name:\s*(.+)", body)
        amount  = re.search(r"in the amount of \$([\d,]+(?:\.\d+)?)", body)
        cat     = re.search(r"reimbursement request for (.+?) in the amount", body)

        results.append({
            "reimbursement_id": reimb.group(1).strip()   if reimb   else None,
            "student":          student.group(1).strip() if student else None,
            "amount":           amount.group(1)           if amount  else None,
            "category":         cat.group(1).strip()     if cat     else None,
            "date":             _email_date(msg),
            "email_id":         stub["id"],
        })

    return results


# ---------------------------------------------------------------------------
# Paid email scanner
# ---------------------------------------------------------------------------

def scan_paid_emails(after_date: str = None) -> list[dict]:
    """
    Scan for SUFS payment emails (any program: FTCPEP, FES, UA, etc.).
    Subject pattern: "<PROGRAM> submitted a payment to you"
    Body: "Payment message: Invoices 33010312-1,33010312-2"

    Returns list of dicts:
      {top_level_ids, line_items, partial, date, email_id}
      partial=True if not all line items for a reimbursement were paid
    """
    svc = _get_gmail_service()
    # Broad subject match catches all program variants (FTCPEP, FES, UA, etc.)
    query = f'from:{SUFS_SENDER} subject:"submitted a payment to you"'
    if after_date:
        query += f" after:{after_date}"

    results = []
    for stub in _list_messages(svc, query):
        msg = svc.users().messages().get(
            userId="me", id=stub["id"], format="full"
        ).execute()
        body = _decode_body(msg)

        # "Payment message: Invoices 33010312-1,33010312-2"
        inv_match = re.search(r"[Ii]nvoices?\s+([\d,\-\s]+)", body)
        line_items: list[str] = []
        top_ids: list[str] = []

        if inv_match:
            raw = inv_match.group(1).strip()
            line_items = [i.strip() for i in re.split(r"[,\s]+", raw) if re.match(r"\d+", i.strip())]
            # Preserve insertion order while deduplicating
            seen: set[str] = set()
            for item in line_items:
                tid = item.split("-")[0]
                if tid not in seen:
                    top_ids.append(tid)
                    seen.add(tid)

        results.append({
            "top_level_ids": top_ids,
            "line_items":    line_items,
            "date":          _email_date(msg),
            "email_id":      stub["id"],
        })

    return results


# ---------------------------------------------------------------------------
# On-hold email scanner
# ---------------------------------------------------------------------------

def scan_on_hold_emails(after_date: str = None) -> list[dict]:
    """
    Scan for SUFS on-hold emails.
    Subject: "Step Up For Students: Your reimbursement request is on hold"
    Body format same as approval: Reimbursement ID + amount.

    Returns list of dicts: {reimbursement_id, amount, student, date, email_id}
    """
    svc = _get_gmail_service()
    query = f'from:{SUFS_SENDER} subject:"reimbursement request is on hold"'
    if after_date:
        query += f" after:{after_date}"

    results = []
    for stub in _list_messages(svc, query):
        msg = svc.users().messages().get(
            userId="me", id=stub["id"], format="full"
        ).execute()
        body = _decode_body(msg)

        reimb   = re.search(r"Reimbursement ID:\s*(\d+)", body)
        student = re.search(r"Student['']s Name:\s*(.+)", body)
        amount  = re.search(r"in the amount of \$([\d,]+(?:\.\d+)?)", body)

        results.append({
            "reimbursement_id": reimb.group(1).strip()   if reimb   else None,
            "student":          student.group(1).strip() if student else None,
            "amount":           amount.group(1)           if amount  else None,
            "date":             _email_date(msg),
            "email_id":         stub["id"],
        })

    return results


# ---------------------------------------------------------------------------
# Remittance Advice PDF scanner
# ---------------------------------------------------------------------------

def scan_remittance_emails(after_date: str = None) -> list[dict]:
    """
    Scan for SUFS Remittance Advice emails from APReports@sufs.org.
    Downloads the PDF attachment, extracts invoice line item IDs, then deletes the temp file.

    Returns list of dicts: {top_level_ids, line_items, amount, date, email_id}
    """
    import base64
    import tempfile
    import os
    import pdfplumber

    svc = _get_gmail_service()
    query = 'from:APReports@sufs.org subject:"Remittance Advice"'
    if after_date:
        query += f" after:{after_date}"

    results = []
    for stub in _list_messages(svc, query):
        msg = svc.users().messages().get(
            userId="me", id=stub["id"], format="full"
        ).execute()

        date = _email_date(msg)

        # Total amount from email body (sanity check only)
        body = _decode_body(msg)
        amt_match = re.search(r"\$([\d,.]+)", body)
        total_amount = amt_match.group(1) if amt_match else ""

        # Find PDF attachment
        line_items: list[str] = []
        top_ids: list[str] = []

        for att in msg.get("payload", {}).get("parts", []):
            filename = att.get("filename", "")
            if not filename.lower().endswith(".pdf"):
                continue

            att_id = att.get("body", {}).get("attachmentId")
            if not att_id:
                continue

            # Download
            att_data = svc.users().messages().attachments().get(
                userId="me", messageId=stub["id"], id=att_id
            ).execute()
            pdf_bytes = base64.urlsafe_b64decode(att_data["data"] + "==")

            # Write to temp file, parse, delete
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            try:
                tmp.write(pdf_bytes)
                tmp.close()
                with pdfplumber.open(tmp.name) as pdf:
                    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                print(f"  [remittance] {date} ${total_amount} — PDF text preview:\n{text[:600]}\n")

                # Invoice IDs look like: 35307411-1  or  35307411
                found = re.findall(r"\b(\d{7,9}-\d+)\b", text)
                if not found:
                    # Fall back to bare IDs if no suffixed ones
                    found = re.findall(r"\b(\d{7,9})\b", text)
                line_items = list(dict.fromkeys(found))  # deduplicate, preserve order
                seen: set[str] = set()
                for item in line_items:
                    tid = item.split("-")[0]
                    if tid not in seen:
                        top_ids.append(tid)
                        seen.add(tid)
            finally:
                os.unlink(tmp.name)

            break  # only one PDF per email

        results.append({
            "top_level_ids": top_ids,
            "line_items":    line_items,
            "total_amount":  total_amount,
            "date":          date,
            "email_id":      stub["id"],
        })

    return results


# ---------------------------------------------------------------------------
# Match emails → sheet rows
# ---------------------------------------------------------------------------

def build_status_updates(
    approved: list[dict],
    paid: list[dict],
    sheet_rows: list[dict],
    reimbursements_raw: list[dict] | None = None,
    remittance: list[dict] | None = None,
) -> list[dict]:
    """
    Match approval and payment emails to sheet rows via column K (reimbursement_id).

    Returns list of {row_index, approved_date, paid_date, partial} dicts
    (only rows that need updating are included).
    """
    # Index sheet rows by reimbursement_id → list[row]
    by_id: dict[str, list[dict]] = {}
    for row in sheet_rows:
        rid = (row.get("reimbursement_id") or "").strip()
        if rid:
            by_id.setdefault(rid, []).append(row)

    # Line item counts per reimbursement (for partial detection)
    item_counts: dict[str, int] = {}
    if reimbursements_raw:
        for r in reimbursements_raw:
            item_counts[r["id"]] = len(r.get("line_items", []))

    updates: dict[int, dict] = {}  # row_index → update dict

    def _ensure(row_index: int) -> dict:
        if row_index not in updates:
            updates[row_index] = {
                "row_index": row_index,
                "approved_date": "", "approved_partial": False,
                "paid_date":     "", "paid_partial":     False,
            }
        return updates[row_index]

    # --- Approved ---
    # SUFS sends one approval email per line item, so count emails per top-level ID
    # and compare against item_counts to detect partial approval.
    from collections import defaultdict
    approved_by_id: dict[str, list] = defaultdict(list)
    for email in approved:
        rid = (email.get("reimbursement_id") or "").strip()
        if rid:
            approved_by_id[rid].append(email)

    for rid, emails in approved_by_id.items():
        if rid not in by_id:
            continue
        total = item_counts.get(rid)
        is_partial = bool(total and len(emails) < total)
        # Use the most recent email date
        latest_date = sorted(emails, key=lambda e: e["date"])[-1]["date"]
        for row in by_id[rid]:
            u = _ensure(row["row_index"])
            u["approved_date"] = latest_date
            u["approved_partial"] = is_partial

    # --- Paid ---
    for email in paid:
        paid_items = set(email.get("line_items", []))
        for rid in email.get("top_level_ids", []):
            if rid not in by_id:
                continue
            total = item_counts.get(rid)
            paid_count = sum(1 for li in paid_items if li.split("-")[0] == rid)
            is_partial = bool(total and paid_count < total)
            for row in by_id[rid]:
                u = _ensure(row["row_index"])
                u["paid_date"] = email["date"]
                u["paid_partial"] = is_partial

    # --- Remittance (treated same as paid) ---
    for email in (remittance or []):
        paid_items = set(email.get("line_items", []))
        for rid in email.get("top_level_ids", []):
            if rid not in by_id:
                continue
            total = item_counts.get(rid)
            paid_count = sum(1 for li in paid_items if li.split("-")[0] == rid)
            is_partial = bool(total and paid_count < total)
            for row in by_id[rid]:
                u = _ensure(row["row_index"])
                u["paid_date"] = email["date"]
                u["paid_partial"] = is_partial

    return list(updates.values())


# ---------------------------------------------------------------------------
# Match emails → Testing tab rows (per-line-item structure)
# ---------------------------------------------------------------------------

def _parse_amount(s: str) -> float:
    """Parse a dollar amount like '76.36', '1,234.56', or '199.99.' to float.

    Extracts the numeric token so trailing punctuation (e.g. a sentence-ending
    period captured by the email regex) doesn't break parsing.
    """
    if not s:
        return 0.0
    m = re.search(r"\d[\d,]*(?:\.\d+)?", str(s))
    if not m:
        return 0.0
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return 0.0


def _amount_matches(email_amount: str, row_price: str, tol: float = 0.02) -> bool:
    """Return True if email dollar amount is within tol of row price."""
    ea = _parse_amount(email_amount)
    rp = _parse_amount(row_price)
    return ea > 0 and abs(ea - rp) <= tol


def build_testing_status_updates(
    approved: list[dict],
    on_hold: list[dict],
    paid: list[dict],
    remittance: list[dict],
    sheet_rows: list[dict],
) -> list[dict]:
    """
    Match emails to 2025-2026 Testing tab rows.

    Rows have sufs_reimb_id like '34405627-1' (line item ID).
    Approved/on-hold emails carry a top-level ID + amount:
      - Match by amount to identify the specific line item row.
      - Fall back to all rows for that top-level ID if no amount match.
    Paid/remittance emails carry explicit line item IDs — matched exactly.

    Status priority: paid > approved > on hold
    Returns list of {row_index, status, on_hold_date, approved_date, paid_date}
    """
    from collections import defaultdict

    # Index rows by top-level ID and by exact line item ID
    by_top_id: dict[str, list[dict]] = defaultdict(list)
    by_line_id: dict[str, dict] = {}
    for row in sheet_rows:
        rid = (row.get("sufs_reimb_id") or "").strip()
        if not rid:
            continue
        top = rid.split("-")[0]
        by_top_id[top].append(row)
        by_line_id[rid] = row

    updates: dict[int, dict] = {}

    def _ensure(row_index: int) -> dict:
        if row_index not in updates:
            updates[row_index] = {
                "row_index":    row_index,
                "status":       "",
                "on_hold_date": "",
                "approved_date": "",
                "paid_date":    "",
            }
        return updates[row_index]

    def _rows_for_email(email: dict, email_type: str) -> list[dict]:
        """
        Return the sheet row(s) this email targets.
        For top-level-ID emails (approved/on_hold): match by amount first,
        fall back to all rows under that top-level ID.
        """
        rid = (email.get("reimbursement_id") or "").strip()
        if not rid:
            return []
        candidates = by_top_id.get(rid, [])
        if not candidates:
            return []
        # Try amount match first (identifies the specific line item)
        amt = email.get("amount", "")
        if amt:
            matched = [r for r in candidates if _amount_matches(amt, r.get("price", ""))]
            if matched:
                return matched
            # Amount given but it matched no single line. Only treat it as a
            # whole-request action if it equals the request total; otherwise
            # it's a partial approval/hold we can't pinpoint — don't over-mark
            # every line item (that's what marked all of 35208591 "approved").
            ea = _parse_amount(amt)
            total = sum(_parse_amount(r.get("price", "")) for r in candidates)
            if ea > 0 and abs(ea - total) <= 0.02:
                return candidates
            return []
        # No amount at all in the email — assume the whole request.
        return candidates

    # --- On hold ---
    for email in on_hold:
        date = email.get("date", "")
        for row in _rows_for_email(email, "on_hold"):
            u = _ensure(row["row_index"])
            u["on_hold_date"] = date
            if not u["status"]:
                u["status"] = "on hold"

    # --- Approved (one email per line item; use amount to target correct row) ---
    for email in approved:
        date = email.get("date", "")
        for row in _rows_for_email(email, "approved"):
            u = _ensure(row["row_index"])
            u["approved_date"] = date
            if u["status"] != "paid":
                u["status"] = "approved"

    # --- Paid / Remittance (line item IDs — exact match) ---
    for source in [paid, remittance]:
        for email in (source or []):
            date = email.get("date", "")
            for lid in email.get("line_items", []):
                row = by_line_id.get(lid)
                if row:
                    u = _ensure(row["row_index"])
                    u["paid_date"] = date
                    u["status"] = "paid"

    return list(updates.values())

"""
Google Sheets access for the SUFS tracking sheet: the Unsubmitted staging tab
and one Line Items tab per scholarship year.
Uses a service account (same credentials as the pickem app).
"""

import os
import re

from src import scholarship_year

SHEET_ID = os.environ.get("SUFS_SHEET_ID", "")

# --- Scholarship-year line-item tabs ---------------------------------------
# Each scholarship year's submitted line items go to their own tab, named from
# src/scholarship_year.py so the July rollover needs no edits here.
# LINE_ITEMS_TAB is the active year: the submission logger always writes here
# (and auto-creates it on first submission).
LINE_ITEMS_TAB = scholarship_year.current_line_items_tab()

# Every scholarship year's line-item tab, oldest → newest. The status scanner,
# the Overview dashboard, and the order-dedup all read/write across ALL of these
# so trailing approvals/payments on a prior year still land and the dashboard
# reflects every active year. A tab that doesn't exist yet is skipped on read.
LINE_ITEMS_TABS = scholarship_year.all_line_items_tabs()

# The Amazon scanner stages NOT-yet-submitted orders here, one row per order
# (SUFS line-item IDs don't exist until a reimbursement is submitted). Shared
# across years — staged purchases aren't year-specific until they're submitted.
UNSUBMITTED_TAB = "Unsubmitted"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Display header for the testing / line-items layout (order matches _TESTING_KEYS).
TESTING_HEADER = [
    "Student", "Item", "Store", "Invoice", "Price", "Date Purchased",
    "Status", "SUFS Reimbursement ID", "Date Submitted",
    "Date On Hold", "Date Approved", "Date Paid",
]

# Header for the Unsubmitted staging tab (one row per Amazon order). Column D is
# the order number, which get_existing_order_numbers reads to skip duplicates.
UNSUBMITTED_HEADER = [
    "Student", "Item", "Store", "Order/Receipt #", "Price", "Date Purchased", "Status",
]

# Columns of every Line Items tab:
# A: Student | B: Item | C: Store | D: Invoice | E: Price | F: Purchase date
# G: Status | H: SUFS Reimbursement ID | I: Date submitted
# J: Date on hold | K: Date approved | L: Date paid
_TESTING_KEYS = [
    "student", "item", "store", "invoice", "price", "purchase_date",
    "status", "sufs_reimb_id", "date_submitted",
    "date_on_hold", "date_approved", "date_paid",
]


def _get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
    creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def get_existing_order_numbers() -> set:
    """Order numbers the scanner should treat as already handled.

    Union of:
      - Unsubmitted!D (orders already staged), and
      - every year's Line Items!D (the Invoice column — already-submitted Amazon
        orders carry their order number here).

    So an order that's been submitted in any year is auto-skipped (no re-staging)
    without any separate "submitted" marking.
    """
    svc = _get_service()

    def _col(tab: str) -> set:
        try:
            rows = svc.spreadsheets().values().get(
                spreadsheetId=SHEET_ID, range=f"{tab}!D:D",
            ).execute().get("values", [])
            return {r[0].strip() for r in rows[1:] if r and r[0].strip()}  # skip header
        except Exception as e:
            print(f"[sheets] Error reading {tab}!D: {e}")
            return set()

    seen = _col(UNSUBMITTED_TAB)
    for tab in LINE_ITEMS_TABS:
        seen |= _col(tab)
    return seen


def append_unsubmitted(rows: list[list]):
    """Append staged rows (UNSUBMITTED_HEADER order) to the Unsubmitted tab."""
    if not rows:
        return
    try:
        create_tab(UNSUBMITTED_TAB, UNSUBMITTED_HEADER)  # no-op if it already exists
        svc = _get_service()
        svc.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=f"{UNSUBMITTED_TAB}!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()
    except Exception as e:
        print(f"[sheets] Error appending to {UNSUBMITTED_TAB}: {e}")
        raise


def append_orders(orders: list):
    """Stage Amazon orders from the scanner, one row per order."""
    append_unsubmitted([
        ["", o.get("description", ""), "Amazon", o.get("order_number", ""),
         o.get("total", ""), o.get("purchase_date", ""), ""]
        for o in orders
    ])


# ---------------------------------------------------------------------------
# Line Items tabs — per-line-item tracking
# ---------------------------------------------------------------------------

class AlreadyLoggedError(ValueError):
    """A SUFS reimbursement has already been logged to a Line Items tab."""


def _is_logged(sufs_id: str) -> bool:
    """True if any Line Items tab already holds a line item of this reimbursement.

    Line item IDs are "<sufs_id>-<n>". Matching the whole pattern keeps "1000000"
    from colliding with an existing "10000001-1".
    """
    pattern = re.compile(rf"{re.escape(sufs_id.strip())}-\d+")
    return any(pattern.fullmatch(r["sufs_reimb_id"].strip()) for r in read_testing_rows())


def log_submission_to_testing(student: str, sufs_id: str, items: list[dict], invoice_filename: str):
    """
    Write one row per selected line item to the active scholarship-year Line
    Items tab (LINE_ITEMS_TAB), creating that tab with headers if it's the first
    submission of the year.
    items: list of item dicts with cost, tax, description, vendor, purchase_date.
    Price = cost + tax.

    Raises AlreadyLoggedError, writing nothing, if this reimbursement is already
    in any year's tab -- logging it again would duplicate every line item.
    """
    if _is_logged(sufs_id):
        raise AlreadyLoggedError(
            f"Reimbursement {sufs_id} is already logged to the sheet; nothing was added."
        )
    from datetime import date as _date
    today = _date.today().strftime("%m/%d/%Y")
    rows = []
    for i, item in enumerate(items, start=1):
        cost = float(item.get("cost") or 0)
        tax  = float(item.get("tax")  or 0)
        price = round(cost + tax, 2)
        rows.append([
            student,
            item.get("description") or "",
            item.get("vendor") or "",
            invoice_filename,
            f"{price:.2f}",
            item.get("purchase_date") or "",
            "submitted",
            f"{sufs_id}-{i}",
            today,
            "", "", "",  # date_on_hold, date_approved, date_paid
        ])
    try:
        create_tab(LINE_ITEMS_TAB, TESTING_HEADER)  # no-op if it already exists
        svc = _get_service()
        svc.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=f"{LINE_ITEMS_TAB}!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()
    except Exception as e:
        print(f"[sheets] Error logging submission to line items tab: {e}")
        raise


def read_testing_rows() -> list[dict]:
    """Read all data rows across every scholarship-year Line Items tab.

    Each row dict carries its source `tab` and a 1-based `row_index` within that
    tab, so callers can route status writes back to the correct cell. Tabs that
    don't exist yet (e.g. a freshly-rolled-over year before its first
    submission) are skipped.
    """
    svc = _get_service()
    data = []
    for tab in LINE_ITEMS_TABS:
        try:
            rows = svc.spreadsheets().values().get(
                spreadsheetId=SHEET_ID,
                range=f"{tab}!A:L",
            ).execute().get("values", [])
        except Exception as e:
            print(f"[sheets] Error reading {tab} rows: {e}")
            continue
        for i, row in enumerate(rows[1:], start=2):  # row 2 = first data row
            padded = row + [""] * (len(_TESTING_KEYS) - len(row))
            data.append({k: padded[j] for j, k in enumerate(_TESTING_KEYS)}
                        | {"row_index": i, "tab": tab})
    return data


def tab_exists(title: str) -> bool:
    svc = _get_service()
    meta = svc.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    return any(s["properties"]["title"] == title for s in meta.get("sheets", []))


def create_tab(title: str, header: list | None = None) -> bool:
    """Create a new tab (optionally writing a header row). Returns False if it already exists."""
    svc = _get_service()
    meta = svc.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    if any(s["properties"]["title"] == title for s in meta.get("sheets", [])):
        return False
    svc.spreadsheets().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()
    if header:
        svc.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=f"{title}!A1",
            valueInputOption="RAW",
            body={"values": [header]},
        ).execute()
    return True


def append_rows(title: str, rows: list[list]):
    """Append rows to a tab by title."""
    if not rows:
        return
    svc = _get_service()
    svc.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=f"{title}!A1",
        valueInputOption="RAW",
        body={"values": rows},
    ).execute()


def batch_write_testing_status(updates: list[dict]):
    """
    Write status and date columns to each row's own Line Items tab.
    Each update: {row_index, tab?, status?, on_hold_date?, approved_date?, paid_date?}
    `tab` names the target Line Items tab; it defaults to the active year's tab
    for back-compat. Column map: G=status, J=on_hold, K=approved, L=paid
    """
    if not updates:
        return
    data = []
    col_map = {"status": "G", "on_hold_date": "J", "approved_date": "K", "paid_date": "L"}
    for u in updates:
        tab = u.get("tab") or LINE_ITEMS_TAB
        row = u["row_index"]
        for field, col in col_map.items():
            val = u.get(field, "")
            if val:
                data.append({"range": f"{tab}!{col}{row}", "values": [[val]]})
    if not data:
        return
    import time
    CHUNK = 50
    try:
        svc = _get_service()
        for i in range(0, len(data), CHUNK):
            chunk = data[i:i + CHUNK]
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=SHEET_ID,
                body={"valueInputOption": "RAW", "data": chunk},
            ).execute()
            if i + CHUNK < len(data):
                time.sleep(1.2)
    except Exception as e:
        print(f"[sheets] Error writing testing status: {e}")
        raise


# ---------------------------------------------------------------------------
# Unsubmitted staging-tab cleanup
# ---------------------------------------------------------------------------
# A staged order leaves the Unsubmitted tab ONLY when the user explicitly asks
# after logging a submission -- never automatically. One purchase is often
# reimbursed separately for each child, and only the user knows when the last
# child has been submitted.
#
# Rows are matched by the Order/Receipt # column: the Amazon scanner fills it
# with the order number, and for other vendors the user pastes their own
# reference there when adding the row by hand.

# Column G of UNSUBMITTED_HEADER.
_UNSUBMITTED_STATUS_COL = "G"


def reference_from_invoice(invoice_filename: str) -> str:
    """The staging reference behind an uploaded receipt, or "" if there is none.

    For Amazon that's the order number the scanner staged (111-7468621-1016217);
    for every other vendor it's whatever the user pasted into the Order/Receipt #
    column when adding the row by hand. Either way it's just the receipt's
    filename without its extension.
    """
    # Not os.path.splitext: it reads ".pdf" as a dotfile named ".pdf" rather
    # than an empty name, which would hand back a bogus reference.
    return re.sub(r"\.[A-Za-z0-9]+$", "", (invoice_filename or "").strip()).strip()


def normalize_reference(value: str) -> str:
    """Fold a reference to its comparable form.

    Matching ignores case, surrounding whitespace, and the difference between
    spaces and underscores -- uploads run through secure_filename(), which turns
    "Target 8-14-26.pdf" into "Target_8-14-26.pdf". Everything else, hyphens
    included, is compared literally, so exact means exact.
    """
    return re.sub(r"[\s_]+", " ", (value or "").strip()).casefold()


def _unsubmitted_rows() -> list[list]:
    """All rows of the Unsubmitted tab, header included, padded to full width."""
    svc = _get_service()
    rows = svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"{UNSUBMITTED_TAB}!A:G",
    ).execute().get("values", [])
    width = len(UNSUBMITTED_HEADER)
    return [list(r) + [""] * (width - len(r)) for r in rows]


def _matching_row_indexes(reference: str) -> list[int]:
    """1-based sheet row numbers whose Order/Receipt # matches this reference."""
    wanted = normalize_reference(reference)
    if not wanted:
        return []
    return [i for i, r in enumerate(_unsubmitted_rows(), start=1)
            if i > 1 and normalize_reference(r[3]) == wanted]


def find_unsubmitted_row(reference: str) -> dict | None:
    """The staged row for this reference, or None if it isn't staged.

    Returns the row's 1-based sheet index plus its display fields, including any
    existing "partial:" note so the caller can show which children are done.
    """
    wanted = normalize_reference(reference)
    if not wanted:
        return None
    for i, r in enumerate(_unsubmitted_rows(), start=1):
        if i > 1 and normalize_reference(r[3]) == wanted:
            return {
                "row_index": i,
                "student": r[0], "item": r[1], "store": r[2],
                "order_number": r[3], "price": r[4],
                "date_purchased": r[5], "status": r[6],
            }
    return None


def delete_unsubmitted_row(reference: str) -> bool:
    """Delete the staged row carrying this Order/Receipt #.

    Returns True if a row was deleted, False if nothing was staged under that
    reference (already removed -- clicking twice is harmless). Raises ValueError
    if it matches more than one row, rather than guessing which to drop.
    """
    matches = _matching_row_indexes(reference)
    if not matches:
        return False
    if len(matches) > 1:
        raise ValueError(
            f"{reference} appears in {UNSUBMITTED_TAB} {len(matches)} times "
            f"(rows {', '.join(str(m) for m in matches)}); refusing to guess. "
            "Remove the duplicates by hand."
        )
    row = matches[0]
    svc = _get_service()
    gid = None
    for sheet in svc.spreadsheets().get(spreadsheetId=SHEET_ID).execute()["sheets"]:
        if sheet["properties"]["title"] == UNSUBMITTED_TAB:
            gid = sheet["properties"]["sheetId"]
            break
    if gid is None:
        raise ValueError(f"{UNSUBMITTED_TAB} tab not found")
    svc.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [
        {"deleteDimension": {"range": {
            "sheetId": gid, "dimension": "ROWS",
            "startIndex": row - 1, "endIndex": row,
        }}}
    ]}).execute()
    return True


def mark_unsubmitted_partial(reference: str, student: str, sufs_id: str) -> str:
    """Record on the staged row that one child has been submitted for it.

    Appends "partial: <student> <sufs_id> (MM/DD)" to the Status column, so a
    multi-child purchase shows its progress at a glance. Repeating the same
    child and reimbursement ID is a no-op. Returns the resulting Status text
    ("" if nothing is staged under that reference).
    """
    row = find_unsubmitted_row(reference)
    if row is None:
        return ""

    from datetime import date as _date
    marker = f"partial: {student.strip()} {sufs_id.strip()}".rstrip()
    existing = (row["status"] or "").strip()
    if marker in existing:
        return existing

    note = f"{marker} ({_date.today().strftime('%m/%d')})"
    updated = f"{existing}; {note}" if existing else note

    svc = _get_service()
    svc.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"{UNSUBMITTED_TAB}!{_UNSUBMITTED_STATUS_COL}{row['row_index']}",
        valueInputOption="RAW",
        body={"values": [[updated]]},
    ).execute()
    return updated


def read_tracked_references() -> tuple[set[str], set[str]]:
    """(submitted, staged): normalised references of every receipt the sheet knows.

    Submitted is the Invoice column of every existing Line Items tab (file name
    without extension); staged is Unsubmitted's Order/Receipt # column.

    Strict, unlike the other readers here: any read error raises. A Line Items
    tab that doesn't exist yet is skipped by checking the tab list first, never
    by swallowing an error -- a silently empty result would make every receipt
    in the folder look untracked.
    """
    svc = _get_service()
    meta = svc.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    titles = {s["properties"]["title"] for s in meta.get("sheets", [])}

    def _column_d(tab: str) -> list[str]:
        rows = svc.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range=f"{tab}!D:D",
        ).execute().get("values", [])
        return [r[0] for r in rows[1:] if r and r[0].strip()]  # skip header

    submitted = {
        normalize_reference(reference_from_invoice(name))
        for tab in LINE_ITEMS_TABS if tab in titles
        for name in _column_d(tab)
    }
    staged = ({normalize_reference(v) for v in _column_d(UNSUBMITTED_TAB)}
              if UNSUBMITTED_TAB in titles else set())
    submitted.discard("")
    staged.discard("")
    return submitted, staged

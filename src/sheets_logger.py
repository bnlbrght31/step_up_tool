"""
Google Sheets logging for SUFS Amazon order tracking.
Uses a service account (same credentials as the pickem app).

Column order: Student | Item | Store | Order number | Price | Date Purchased | Status | ...
"""

import os

SHEET_ID = os.environ.get("SUFS_SHEET_ID", "")
TAB = "2025-2026"

# --- Scholarship-year line-item tabs ---------------------------------------
# The scholarship year runs Jul 1 – Jun 30. Each year's submitted line items go
# to their own tab. LINE_ITEMS_TAB is the *active* year: the submission logger
# always writes here (and auto-creates it on first submission).
#
# ROLLOVER (do this each July): point LINE_ITEMS_TAB at the new year's tab and
# append that name to LINE_ITEMS_TABS.
LINE_ITEMS_TAB = "2026-2027 Line Items"

# Every scholarship year's line-item tab, oldest → newest. The status scanner,
# the Overview dashboard, and the order-dedup all read/write across ALL of these
# so trailing approvals/payments on a prior year still land and the dashboard
# reflects every active year. A tab that doesn't exist yet is skipped on read.
LINE_ITEMS_TABS = ["2025-2026 Line Items", LINE_ITEMS_TAB]

# Back-compat alias for the active submission tab.
TESTING_TAB = LINE_ITEMS_TAB
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
    "Student", "Item", "Store", "Order Number", "Price", "Date Purchased", "Status",
]

# Columns for TESTING_TAB:
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


def read_all_rows() -> list[dict]:
    """
    Read all data rows from the 2025-2026 tab.
    Returns list of dicts with keys matching column headers + row_index (1-based, skipping header).
    """
    try:
        svc = _get_service()
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f"{TAB}!A1:M500",
        ).execute()
        rows = result.get("values", [])
        if not rows:
            return []
        header = rows[0]
        keys = ["student", "item", "store", "order_number", "price",
                "date_purchased", "status", "date_submitted", "date_reimbursed",
                "date_paid", "reimbursement_id", "sufs_approved_date", "sufs_paid_date"]
        data = []
        for i, row in enumerate(rows[1:], start=2):  # row 2 = first data row
            padded = row + [""] * (len(keys) - len(row))
            data.append({k: padded[j] for j, k in enumerate(keys)} | {"row_index": i})
        return data
    except Exception as e:
        print(f"[sheets] Error reading rows: {e}")
        return []


def write_reimbursement_id(row_index: int, reimb_id: str):
    """Write a reimbursement ID to column K of the given row."""
    batch_write_reimbursement_ids({row_index: reimb_id})


def batch_write_reimbursement_ids(row_to_id: dict[int, str]):
    """Write multiple reimbursement IDs to column K in a single API call."""
    if not row_to_id:
        return
    import time
    CHUNK = 50
    items = list(row_to_id.items())
    try:
        svc = _get_service()
        for i in range(0, len(items), CHUNK):
            chunk = items[i:i + CHUNK]
            svc.spreadsheets().values().batchUpdate(
                spreadsheetId=SHEET_ID,
                body={
                    "valueInputOption": "RAW",
                    "data": [
                        {"range": f"{TAB}!K{row_index}", "values": [[reimb_id]]}
                        for row_index, reimb_id in chunk
                    ],
                },
            ).execute()
            if i + CHUNK < len(items):
                time.sleep(1.2)
    except Exception as e:
        print(f"[sheets] Error batch-writing reimbursement IDs: {e}")
        raise


def batch_write_sufs_status(updates: list[dict]):
    """
    Write SUFS approved/paid dates to columns L and M.
    Each update: {row_index, approved_date, paid_date}  (empty string = skip)
    Single API call for all rows.
    """
    if not updates:
        return
    data = []
    for u in updates:
        row = u["row_index"]
        if u.get("approved_date"):
            label = f"Partial ({u['approved_date']})" if u.get("approved_partial") else u["approved_date"]
            data.append({"range": f"{TAB}!L{row}", "values": [[label]]})
        if u.get("paid_date"):
            label = f"Partial ({u['paid_date']})" if u.get("paid_partial") else u["paid_date"]
            data.append({"range": f"{TAB}!M{row}", "values": [[label]]})
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
        print(f"[sheets] Error writing SUFS status: {e}")
        raise


def append_order(order: dict):
    """
    Append one row to the 2025-2026 tab.
    Columns A-G: Student | Item | Store | Order number | Price | Date Purchased | Status
    Student and Status are left blank for manual entry.
    """
    row = [
        "",                              # A: Student (fill in manually)
        order.get("description", ""),   # B: Item
        "Amazon",                        # C: Store
        order.get("order_number", ""),  # D: Order number
        order.get("total", ""),         # E: Price
        order.get("purchase_date", ""), # F: Date Purchased
        "",                              # G: Status (fill in manually)
    ]
    try:
        create_tab(UNSUBMITTED_TAB, UNSUBMITTED_HEADER)  # no-op if it already exists
        svc = _get_service()
        svc.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=f"{UNSUBMITTED_TAB}!A1",
            valueInputOption="RAW",
            body={"values": [row]},
        ).execute()
    except Exception as e:
        print(f"[sheets] Error appending row: {e}")
        raise


def append_orders(orders: list):
    """Append multiple orders in a single API call."""
    if not orders:
        return
    rows = [
        [
            "",
            o.get("description", ""),
            "Amazon",
            o.get("order_number", ""),
            o.get("total", ""),
            o.get("purchase_date", ""),
            "",
        ]
        for o in orders
    ]
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
        print(f"[sheets] Error batch appending rows: {e}")
        raise


# ---------------------------------------------------------------------------
# 2025-2026 Testing tab — per-line-item tracking
# ---------------------------------------------------------------------------

def log_submission_to_testing(student: str, sufs_id: str, items: list[dict], invoice_filename: str):
    """
    Write one row per selected line item to the active scholarship-year Line
    Items tab (LINE_ITEMS_TAB), creating that tab with headers if it's the first
    submission of the year.
    items: list of item dicts with cost, tax, description, vendor, purchase_date.
    Price = cost + tax.
    """
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
                range=f"{tab}!A1:L500",
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

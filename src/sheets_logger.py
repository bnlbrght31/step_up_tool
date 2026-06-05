"""
Google Sheets logging for SUFS Amazon order tracking.
Uses a service account (same credentials as the pickem app).

The sheet has two tabs; we read/write only "2025-2026".
Column order: Student | Item | Store | Order number | Price | Date Purchased | Status | ...
"""

import os

SHEET_ID = "1RgX0mHVHt86EuXka43bgK2gXnl4DqW6FbssCWe5Q6xk"
TAB = "2025-2026"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
    creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def get_existing_order_numbers() -> set:
    """Read column D (Order number) from the current year tab and return as a set."""
    try:
        svc = _get_service()
        result = svc.spreadsheets().values().get(
            spreadsheetId=SHEET_ID,
            range=f"{TAB}!D:D",
        ).execute()
        rows = result.get("values", [])
        # Row 0 is the header; skip it
        return {row[0].strip() for row in rows[1:] if row and row[0].strip()}
    except Exception as e:
        print(f"[sheets] Error reading order numbers: {e}")
        return set()


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
        svc = _get_service()
        svc.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=f"{TAB}!A1",
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
        svc = _get_service()
        svc.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=f"{TAB}!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()
    except Exception as e:
        print(f"[sheets] Error batch appending rows: {e}")
        raise

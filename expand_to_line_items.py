"""
One-time migration: expand matched 2025-2026 (main tab) rows into the
2025-2026 Testing layout — one row per scraped line item — in a new
'2025-2026 Line Items' tab.

Copies what we have from the main tab + the line-item scrape
(reimbursements_raw.json). Leaves Date On Hold / Date Approved / Date Paid
blank so a status scan can fill them fresh.

Only rows that already carry a reimbursement ID (col K) and match the scrape
are expanded; rows without an ID (prior-year or not-yet-submitted) are skipped.

    python expand_to_line_items.py            # dry run (preview only)
    python expand_to_line_items.py --write    # create the tab and write
"""

import json
import sys

from dotenv import load_dotenv

load_dotenv()

from src.sheets_logger import (
    LINE_ITEMS_TAB,
    TESTING_HEADER,
    append_rows,
    create_tab,
    read_all_rows,
    tab_exists,
)

RAW = "reimbursements_raw.json"
STATUS_MAP = {"Submitted": "submitted", "Paid": "paid", "Approved": "approved", "Denied": "denied"}


def _price(amount) -> str:
    s = str(amount).replace("$", "").replace(",", "").strip()
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return s


def build_rows():
    scrape = {r["id"]: r for r in json.load(open(RAW))}
    out = []
    matched = 0
    for r in read_all_rows():
        rid = (r.get("reimbursement_id") or "").strip()
        if not rid or rid not in scrape:
            continue
        matched += 1
        reimb = scrape[rid]
        for li in reimb.get("line_items", []):
            status = li.get("status", "")
            out.append([
                r.get("student", ""),                              # A Student
                li.get("description", ""),                         # B Item
                r.get("store", "") or reimb.get("provider", ""),   # C Store
                r.get("order_number", ""),                         # D Invoice (order ref)
                _price(li.get("amount", "")),                      # E Price (per line item)
                r.get("date_purchased", ""),                       # F Date Purchased
                STATUS_MAP.get(status, status.lower()),            # G Status
                li.get("line_id", ""),                             # H SUFS Reimbursement ID
                r.get("date_submitted", ""),                       # I Date Submitted
                "",                                                # J Date On Hold
                "",                                                # K Date Approved (left blank)
                "",                                                # L Date Paid (left blank)
            ])
    return out, matched


def main():
    write = "--write" in sys.argv
    rows, matched = build_rows()
    print(f"matched reimbursements: {matched}")
    print(f"line-item rows to write: {len(rows)}")
    print("\nfirst 8 rows:")
    for row in rows[:8]:
        print("  ", row)

    if not write:
        print("\nDRY RUN — re-run with --write to create the tab and write these rows.")
        return

    if tab_exists(LINE_ITEMS_TAB):
        print(f"\nTab '{LINE_ITEMS_TAB}' already exists — aborting to avoid duplicates.")
        print("Delete that tab first if you want to regenerate.")
        return

    create_tab(LINE_ITEMS_TAB, TESTING_HEADER)
    append_rows(LINE_ITEMS_TAB, rows)
    print(f"\nDone. Created '{LINE_ITEMS_TAB}' and wrote {len(rows)} rows.")


if __name__ == "__main__":
    main()

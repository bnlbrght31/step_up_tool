"""
Write high-confidence reimbursement ID matches to column K of the tracking sheet.
Loads match_report.json produced by test_match_reimbursements.py — no re-scraping needed.
"""

import json
import os
from dotenv import load_dotenv
load_dotenv()

from src.sheets_logger import batch_write_reimbursement_ids

REPORT_FILE = "match_report.json"


def main():
    if not os.path.exists(REPORT_FILE):
        print(f"ERROR: {REPORT_FILE} not found. Run test_match_reimbursements.py first.")
        return

    with open(REPORT_FILE) as f:
        matches = json.load(f)

    high = [m for m in matches if m["confidence"] == "high" and m["sheet_row_index"]]
    print(f"High-confidence matches to write: {len(high)}")
    print()

    # Preview
    for m in high:
        print(f"  Row {m['sheet_row_index']:3d}  col K = {m['reimb_id']:12s}"
              f"  ({m['sufs_provider']:20s}  {m['sufs_amount']:>8}  {m['sufs_date']})"
              f"  → sheet: {m['sheet_store']:20s}  {m['sheet_price']:>8}  submitted {m['sheet_date_submitted']}")

    print()
    confirm = input(f"Write {len(high)} reimbursement IDs to sheet? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    row_to_id = {m["sheet_row_index"]: m["reimb_id"] for m in high}
    try:
        batch_write_reimbursement_ids(row_to_id)
        print(f"\nDone. {len(row_to_id)} reimbursement IDs written.")
    except Exception as e:
        print(f"\nERROR: {e}")


if __name__ == "__main__":
    main()

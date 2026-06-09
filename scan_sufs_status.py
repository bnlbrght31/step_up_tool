"""
Scan Gmail for SUFS approval and payment emails, match to tracking sheet,
and write dates to columns L (Approved) and M (Paid).

Run any time after receiving SUFS emails. Safe to re-run — skips rows
that already have values unless --overwrite is passed.
"""

import json
import os
import sys
from dotenv import load_dotenv
load_dotenv()

from src.sufs_email_scanner import scan_approved_emails, scan_paid_emails, scan_remittance_emails, build_status_updates
from src.sheets_logger import read_all_rows, batch_write_sufs_status

AFTER_DATE = "2025/07/01"  # scholarship year start — only look at emails from here on


def main():
    overwrite = "--overwrite" in sys.argv

    print("=== Reading tracking sheet ===")
    sheet_rows = read_all_rows()
    print(f"  {len(sheet_rows)} rows")

    # Load raw reimbursement data for partial-payment detection (optional)
    reimbursements_raw = None
    if os.path.exists("reimbursements_raw.json"):
        with open("reimbursements_raw.json") as f:
            reimbursements_raw = json.load(f)
        print(f"  {len(reimbursements_raw)} reimbursements loaded for partial detection")
    else:
        print("  (reimbursements_raw.json not found — partial payment detection disabled)")

    print("\n=== Scanning approval emails ===")
    approved = scan_approved_emails(after_date=AFTER_DATE)
    print(f"  {len(approved)} approval email(s) found")

    print("\n=== Scanning payment emails ===")
    paid = scan_paid_emails(after_date=AFTER_DATE)
    print(f"  {len(paid)} payment email(s) found")

    print("\n=== Scanning remittance advice emails ===")
    remittance = scan_remittance_emails(after_date=AFTER_DATE)
    print(f"  {len(remittance)} remittance email(s) found")

    # Debug: show what IDs the paid emails reference vs what's in the sheet
    sheet_ids = {(r.get("reimbursement_id") or "").strip() for r in sheet_rows if r.get("reimbursement_id", "").strip()}
    print(f"\n  Sheet has {len(sheet_ids)} rows with a reimbursement ID in column K")
    for email in paid:
        ids = email.get("top_level_ids", [])
        items = email.get("line_items", [])
        matched = [i for i in ids if i in sheet_ids]
        print(f"  Payment {email['date']}  items={items}  top_ids={ids}  matched={matched or 'NONE'}")

    print("\n=== Matching to sheet rows ===")
    updates = build_status_updates(approved, paid, sheet_rows, reimbursements_raw, remittance)

    if not updates:
        print("  No matches found — nothing to write.")
        return

    # Filter out rows that already have values (unless --overwrite)
    if not overwrite:
        filtered = []
        for u in updates:
            row = next((r for r in sheet_rows if r["row_index"] == u["row_index"]), None)
            skip_approved = u["approved_date"] and row and row.get("sufs_approved_date", "").strip()
            skip_paid = u["paid_date"] and row and row.get("sufs_paid_date", "").strip()
            if not skip_approved and not skip_paid:
                filtered.append(u)
            # Partial update: only write the field that's missing
            elif not skip_approved and u["approved_date"]:
                filtered.append({**u, "paid_date": ""})
            elif not skip_paid and u["paid_date"]:
                filtered.append({**u, "approved_date": ""})
        updates = filtered

    if not updates:
        print("  All matched rows already have values. Use --overwrite to force.")
        return

    # Preview
    print(f"\n  {len(updates)} row(s) to update:\n")
    for u in updates:
        row = next((r for r in sheet_rows if r["row_index"] == u["row_index"]), {})
        def _label(date, partial):
            return f"Partial ({date})" if partial else date
        approved_str = f"  L={_label(u['approved_date'], u.get('approved_partial'))}" if u.get("approved_date") else ""
        paid_str     = f"  M={_label(u['paid_date'],     u.get('paid_partial'))}"     if u.get("paid_date")     else ""
        print(f"  Row {u['row_index']:3d}{approved_str}{paid_str}"
              f"  ← {row.get('store',''):15s}  {row.get('item','')[:40]}")

    print()
    confirm = input(f"Write {len(updates)} update(s) to sheet? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    batch_write_sufs_status(updates)
    print(f"\nDone. {len(updates)} row(s) updated.")


if __name__ == "__main__":
    main()

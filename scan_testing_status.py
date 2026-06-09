"""
Scan Gmail for SUFS status emails and write dates to the '2025-2026 Testing' tab.

Columns updated:
  G = Status (on hold / approved / paid)
  J = Date on hold
  K = Date approved
  L = Date paid

Safe to re-run — skips rows that already have values unless --overwrite is passed.
"""

import sys
from dotenv import load_dotenv
load_dotenv()

from src.sufs_email_scanner import (
    scan_approved_emails,
    scan_on_hold_emails,
    scan_paid_emails,
    scan_remittance_emails,
    build_testing_status_updates,
)
from src.sheets_logger import read_testing_rows, batch_write_testing_status

AFTER_DATE = "2025/07/01"


def main():
    overwrite = "--overwrite" in sys.argv

    print("=== Reading 2025-2026 Testing tab ===")
    sheet_rows = read_testing_rows()
    print(f"  {len(sheet_rows)} rows")

    print("\n=== Scanning on-hold emails ===")
    on_hold = scan_on_hold_emails(after_date=AFTER_DATE)
    print(f"  {len(on_hold)} on-hold email(s) found")

    print("\n=== Scanning approval emails ===")
    approved = scan_approved_emails(after_date=AFTER_DATE)
    print(f"  {len(approved)} approval email(s) found")

    print("\n=== Scanning payment emails ===")
    paid = scan_paid_emails(after_date=AFTER_DATE)
    print(f"  {len(paid)} payment email(s) found")

    print("\n=== Scanning remittance advice emails ===")
    remittance = scan_remittance_emails(after_date=AFTER_DATE)
    print(f"  {len(remittance)} remittance email(s) found")

    print("\n=== Matching to sheet rows ===")
    updates = build_testing_status_updates(approved, on_hold, paid, remittance, sheet_rows)

    if not updates:
        print("  No matches found — nothing to write.")
        return

    # Filter out rows that already have all relevant values (unless --overwrite)
    if not overwrite:
        filtered = []
        for u in updates:
            row = next((r for r in sheet_rows if r["row_index"] == u["row_index"]), {})
            has_on_hold  = row.get("date_on_hold", "").strip()
            has_approved = row.get("date_approved", "").strip()
            has_paid     = row.get("date_paid", "").strip()

            new_u = {**u}
            if has_on_hold  and not overwrite: new_u["on_hold_date"]  = ""
            if has_approved and not overwrite: new_u["approved_date"] = ""
            if has_paid     and not overwrite: new_u["paid_date"]     = ""
            # Only include if at least one new value to write
            if any(new_u.get(f) for f in ("on_hold_date", "approved_date", "paid_date")):
                filtered.append(new_u)
        updates = filtered

    if not updates:
        print("  All matched rows already have values. Use --overwrite to force.")
        return

    # Preview
    print(f"\n  {len(updates)} row(s) to update:\n")
    for u in updates:
        row = next((r for r in sheet_rows if r["row_index"] == u["row_index"]), {})
        parts = []
        if u.get("on_hold_date"):  parts.append(f"J={u['on_hold_date']}")
        if u.get("approved_date"): parts.append(f"K={u['approved_date']}")
        if u.get("paid_date"):     parts.append(f"L={u['paid_date']}")
        if u.get("status"):        parts.append(f"G={u['status']}")
        print(f"  Row {u['row_index']:3d}  {', '.join(parts)}"
              f"  ← {row.get('sufs_reimb_id',''):14s}  {row.get('item','')[:40]}")

    print()
    confirm = input(f"Write {len(updates)} update(s) to sheet? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    batch_write_testing_status(updates)
    print(f"\nDone. {len(updates)} row(s) updated.")


if __name__ == "__main__":
    main()

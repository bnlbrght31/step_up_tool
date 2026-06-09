"""
Scrape all SUFS reimbursements and match to tracking sheet rows.
Prints a report — does NOT write anything to the sheet.
Run with SUFS Chrome open on the Reimbursements page.
"""

import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

from src.reimbursement_scraper import scrape_all, match_to_sheet
from src.sheets_logger import read_all_rows

CDP_PORT = int(os.environ.get("CDP_PORT", 9222))


async def main():
    print("=== Step 1: Reading tracking sheet ===")
    sheet_rows = read_all_rows()
    print(f"  {len(sheet_rows)} rows in sheet")

    print("\n=== Step 2: Scraping SUFS portal ===")
    reimbursements = await scrape_all(CDP_PORT)
    total_items = sum(len(r["line_items"]) for r in reimbursements)
    print(f"\n  {len(reimbursements)} reimbursements, {total_items} total line items")

    # Save raw scrape for inspection
    with open("reimbursements_raw.json", "w") as f:
        json.dump(reimbursements, f, indent=2)
    print("  Saved raw data to reimbursements_raw.json")

    print("\n=== Step 3: Matching ===")
    matches = match_to_sheet(reimbursements, sheet_rows)

    # Summary
    by_confidence = {"high": [], "medium": [], "low": [], "no match": []}
    for m in matches:
        by_confidence[m["confidence"]].append(m)

    print(f"\n  High confidence:   {len(by_confidence['high'])}")
    print(f"  Medium confidence: {len(by_confidence['medium'])}")
    print(f"  Low confidence:    {len(by_confidence['low'])}")
    print(f"  No match:          {len(by_confidence['no match'])}")

    # Print each group
    def print_match(m):
        items = f"({m.get('num_line_items', '?')} item(s))"
        print(f"    {m['reimb_id']:12s} {items:12s}  {m['sufs_amount']:>8}  {m['sufs_provider']:20s}  {m['sufs_student']:20s}  {m['sufs_date']}")
        if m["sheet_row_index"]:
            print(f"      → row {m['sheet_row_index']:3d}  {m['sheet_store']:20s}  {m['sheet_price']:>8}  {m['sheet_item'][:40]}  (submitted {m['sheet_date_submitted']})")

    print("\n--- HIGH confidence ---")
    for m in by_confidence["high"][:20]:
        print_match(m)
    if len(by_confidence["high"]) > 20:
        print(f"    ... and {len(by_confidence['high']) - 20} more")

    print("\n--- MEDIUM confidence ---")
    for m in by_confidence["medium"]:
        print_match(m)

    print("\n--- LOW confidence (review needed) ---")
    for m in by_confidence["low"]:
        print_match(m)

    print("\n--- NO MATCH ---")
    for m in by_confidence["no match"]:
        print_match(m)

    # Save full match report
    with open("match_report.json", "w") as f:
        json.dump(matches, f, indent=2)
    print("\nFull match report saved to match_report.json")


asyncio.run(main())

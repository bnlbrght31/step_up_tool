"""
Inspect the SUFS reimbursement list page — scrape first 5 rows
and expand each to see what line-item data is available.
"""

import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

from playwright.async_api import async_playwright

CDP_PORT = int(os.environ.get("CDP_PORT", 9222))
REIMBURSEMENT_URL = "https://apply.stepupforstudents.org/Reimbursement"


async def inspect():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()

        # List all open pages
        print("Open pages:")
        for pg in ctx.pages:
            print(f"  {pg.url}")

        # Use the already-open SUFS tab
        page = None
        for pg in ctx.pages:
            if "stepupforstudents" in pg.url and "Reimbursement" in pg.url:
                page = pg
                break
        if not page:
            for pg in ctx.pages:
                if "stepupforstudents" in pg.url:
                    page = pg
                    break
        if not page:
            print("No SUFS tab found — open the Reimbursements page in SUFS Chrome first")
            await browser.close()
            return

        print(f"\nUsing tab: {page.url}")
        await page.wait_for_timeout(1000)

        # --- Scrape top-level rows ---
        rows = await page.query_selector_all("table tbody tr")
        print(f"\nFound {len(rows)} top-level rows on first page")

        results = []
        for i, row in enumerate(rows[:5]):  # sample first 5
            cells = await row.query_selector_all("td")
            cell_texts = [await c.inner_text() for c in cells]
            print(f"\nRow {i+1} cells: {cell_texts}")

            # Try clicking the expand button (▶ in first cell)
            expand_btn = await row.query_selector("td:first-child button, td:first-child [class*='expand'], td:first-child [class*='toggle'], td:first-child svg, td:first-child i")
            if not expand_btn:
                # Try clicking the first cell itself
                expand_btn = cells[0] if cells else None

            if expand_btn:
                try:
                    await expand_btn.click()
                    await page.wait_for_timeout(1000)

                    # Look for sub-rows that appeared after this row
                    # Common patterns: sibling tr with class, or a detail div
                    page_html = await page.content()
                    # Check for any newly visible sub-table rows
                    detail_rows = await page.query_selector_all("table tbody tr.detail, table tbody tr.sub-row, table tbody tr[class*='expand'], table tbody tr[class*='child'], table tbody tr[class*='detail']")
                    print(f"  Detail rows after expand: {len(detail_rows)}")
                    for dr in detail_rows:
                        dt = await dr.inner_text()
                        print(f"    Detail: {dt[:200]}")

                    # Also check for any visible nested tables
                    nested = await row.query_selector_all("table, [class*='detail'], [class*='expand'], [class*='child']")
                    for n in nested:
                        nt = await n.inner_text()
                        if nt.strip():
                            print(f"    Nested: {nt[:300]}")

                    # Click to collapse before moving on
                    await expand_btn.click()
                    await page.wait_for_timeout(500)
                except Exception as e:
                    print(f"  Expand click error: {e}")

        # --- Check pagination ---
        print("\n--- Pagination ---")
        pagination = await page.query_selector_all("[class*='page'], [class*='pagination'], nav")
        for pg_el in pagination:
            pt = await pg_el.inner_text()
            print(f"Pagination element: {pt[:100]}")

        # Check total count text
        total_el = await page.query_selector("text=/of \\d+/")
        if total_el:
            print(f"Total indicator: {await total_el.inner_text()}")

        # --- Check "Details" link destination ---
        details_links = await page.query_selector_all("a:has-text('Details')")
        if details_links:
            href = await details_links[0].get_attribute("href")
            print(f"\nFirst 'Details' link href: {href}")

        await browser.close()


asyncio.run(inspect())

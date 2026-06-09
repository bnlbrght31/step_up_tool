"""
Scrapes all reimbursements from the SUFS portal and matches them to
rows in the tracking Google Sheet by amount + student + provider.
"""

import asyncio
import os
import re
from playwright.async_api import async_playwright

REIMBURSEMENT_URL = "https://apply.stepupforstudents.org/Reimbursement"


# ---------------------------------------------------------------------------
# Portal scraping
# ---------------------------------------------------------------------------

async def _scrape_page(page) -> list[dict]:
    """Scrape one page of reimbursements, expanding each row for line items."""
    reimbursements = []

    # rz-data-row is the class for all rows; main rows have an empty first cell (expand toggle)
    # and the reimbursement ID in the second cell
    rows = await page.query_selector_all("table tbody tr.rz-data-row")

    for row in rows:
        cells = await row.query_selector_all("td")
        if len(cells) < 8:
            continue
        texts = [t.strip() for t in [await c.inner_text() for c in cells]]

        # Skip injected line item rows — they have content in cell[0], main rows don't
        if texts and texts[0] and "-" in texts[0]:
            continue

        reimb = {
            "id":       texts[1] if len(texts) > 1 else "",
            "program":  texts[2] if len(texts) > 2 else "",
            "date":     texts[3] if len(texts) > 3 else "",
            "provider": texts[4] if len(texts) > 4 else "",
            "student":  texts[5] if len(texts) > 5 else "",
            "amount":   texts[6] if len(texts) > 6 else "",
            "status":   texts[7] if len(texts) > 7 else "",
            "line_items": [],
        }

        if not reimb["id"] or not reimb["id"].isdigit():
            continue

        # Click expand, then find injected line item rows by their ID prefix
        try:
            await cells[0].click()
            await page.wait_for_timeout(800)

            all_rows = await page.query_selector_all("table tbody tr.rz-data-row")
            for r in all_rows:
                rc = await r.query_selector_all("td")
                if not rc:
                    continue
                first = (await rc[0].inner_text()).strip()
                if not first.startswith(f"{reimb['id']}-"):
                    continue
                sc_texts = [t.strip() for t in [await c.inner_text() for c in rc]]
                reimb["line_items"].append({
                    "line_id":      sc_texts[0],
                    "category":     sc_texts[1] if len(sc_texts) > 1 else "",
                    "type":         sc_texts[2] if len(sc_texts) > 2 else "",
                    "description":  sc_texts[3] if len(sc_texts) > 3 else "",
                    "amount":       sc_texts[4] if len(sc_texts) > 4 else "",
                    "status":       sc_texts[5] if len(sc_texts) > 5 else "",
                    "payment_date": sc_texts[6] if len(sc_texts) > 6 else "",
                })

            # Collapse
            await cells[0].click()
            await page.wait_for_timeout(300)
        except Exception as e:
            print(f"  [scraper] Warning expanding {reimb['id']}: {e}")

        reimbursements.append(reimb)
        print(f"  Scraped {reimb['id']} ({reimb['provider'] or 'no provider'}, {reimb['amount']}, {len(reimb['line_items'])} line item(s))")

    return reimbursements


async def scrape_all(cdp_port: int = 9222) -> list[dict]:
    """Scrape all reimbursements across all pages."""
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()

        page = None
        for pg in ctx.pages:
            if pg.url.startswith("https://apply.stepupforstudents.org/Reimbursement"):
                page = pg
                break
        if not page:
            for pg in ctx.pages:
                if pg.url.startswith("https://apply.stepupforstudents.org"):
                    page = pg
                    break
        if not page:
            raise RuntimeError("No SUFS tab found. Open apply.stepupforstudents.org/Reimbursement in SUFS Chrome first.")

        print(f"Using tab: {page.url}")
        await page.wait_for_timeout(1000)

        all_reimbursements = []
        page_num = 1

        while True:
            print(f"\n--- Page {page_num} ---")
            batch = await _scrape_page(page)
            all_reimbursements.extend(batch)

            # Capture first row ID so we can detect when the page actually changes
            first_id = await page.evaluate("""() => {
                for (const row of document.querySelectorAll('table tbody tr.rz-data-row')) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length > 1) {
                        const t = cells[1].innerText.trim();
                        if (t && /^\\d+$/.test(t)) return t;
                    }
                }
                return null;
            }""")

            # The Radzen grid pagination uses icon-only buttons (no text) outside table rows.
            # Order is always: First | Prev | Next | Last — so Next is index 2 (0-based).
            at_last = await page.evaluate("""() => {
                // Collect icon-only pager buttons that are NOT inside a table <tr>
                const allIconBtns = Array.from(document.querySelectorAll('.rz-button-icon-only'));
                const pagerBtns = allIconBtns.filter(b => !b.closest('tr'));

                if (pagerBtns.length === 0) return 'not_found:0_pager_btns';

                // Layout variants:
                //   2 buttons → Prev | Next  (Next = index 1)
                //   4 buttons → First | Prev | Next | Last  (Next = index 2)
                const nextBtn = pagerBtns.length === 2 ? pagerBtns[1] : pagerBtns[2];
                if (nextBtn.disabled || nextBtn.hasAttribute('disabled')
                    || nextBtn.getAttribute('aria-disabled') === 'true') return 'disabled';
                nextBtn.click();
                return 'clicked_next';
            }""")

            print(f"  [pager] {at_last}")

            if at_last.startswith("not_found") or at_last.startswith("disabled"):
                break

            # Wait for the first row's ID to change (proves new page loaded)
            if first_id:
                try:
                    await page.wait_for_function(
                        f"""() => {{
                            for (const row of document.querySelectorAll('table tbody tr.rz-data-row')) {{
                                const cells = row.querySelectorAll('td');
                                if (cells.length > 1) {{
                                    const t = cells[1].innerText.trim();
                                    if (t && /^\\d+$/.test(t)) return t !== '{first_id}';
                                }}
                            }}
                            return false;
                        }}""",
                        timeout=8000,
                    )
                except Exception:
                    print("  [scraper] Table did not change after click — stopping pagination")
                    break
            else:
                await page.wait_for_timeout(2500)

            page_num += 1

        await browser.close()
        return all_reimbursements


# ---------------------------------------------------------------------------
# Matching against the Google Sheet
# ---------------------------------------------------------------------------

def _parse_amount(s: str) -> float | None:
    """Parse '$75.26' or '75.26' → 75.26"""
    try:
        return float(re.sub(r"[^\d.]", "", s))
    except Exception:
        return None


def _normalize_date(s: str) -> str:
    """Normalize M/D/YYYY or MM/DD/YY etc. to MM/DD/YYYY for comparison."""
    from datetime import datetime
    s = s.strip()
    if not s:
        return ""
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).strftime("%m/%d/%Y")
        except ValueError:
            pass
    return s


def _first_name(full_name: str) -> str:
    return full_name.strip().split()[0].lower() if full_name.strip() else ""


def match_to_sheet(reimbursements: list[dict], sheet_rows: list[dict], amount_tolerance: float = 1.00) -> list[dict]:
    """
    Match each top-level SUFS reimbursement to a sheet row.

    The sheet tracks the total reimbursement amount — individual SUFS line items
    within a single submission don't map to separate sheet rows.

    Primary key: Date Submitted (col H) == SUFS submission date.
    Secondary: top-line amount within tolerance, student name, store/provider.
    """
    from collections import defaultdict

    # Index sheet rows by normalized submission date → list of rows
    date_index: dict[str, list] = defaultdict(list)
    for row in sheet_rows:
        d = _normalize_date(row.get("date_submitted", ""))
        if d:
            date_index[d].append(row)

    used_row_indices: set[int] = set()
    matches = []

    for reimb in reimbursements:
        r_date_raw = reimb.get("date", "")
        r_date = _normalize_date(r_date_raw)
        r_provider = reimb.get("provider", "").lower()
        r_student_first = _first_name(reimb.get("student", ""))
        r_amt = _parse_amount(reimb.get("amount", ""))

        if r_amt is None:
            continue

        # Candidates: same submission date, or fall back to all rows
        candidates = date_index.get(r_date, []) or sheet_rows

        best = None
        best_score = -1

        for row in candidates:
            if row["row_index"] in used_row_indices:
                continue
            if row.get("reimbursement_id", "").strip():
                continue  # already matched

            row_amt = _parse_amount(row.get("price", ""))
            if row_amt is None or abs(row_amt - r_amt) > amount_tolerance:
                continue

            score = 0

            # Date match
            row_date = _normalize_date(row.get("date_submitted", ""))
            if r_date and row_date == r_date:
                score += 20

            # Amount closeness (max 10 pts)
            score += max(0, 10 - abs(row_amt - r_amt) * 10)

            # Student match
            row_student = row.get("student", "").lower()
            if r_student_first and r_student_first in row_student:
                score += 8
            elif not row_student.strip():
                score += 2

            # Provider / store match
            row_store = row.get("store", "").lower()
            if r_provider and r_provider in row_store:
                score += 5
            elif r_provider and row_store and row_store in r_provider:
                score += 3

            if score > best_score:
                best_score = score
                best = row

        if best_score >= 28:
            confidence = "high"
        elif best_score >= 15:
            confidence = "medium"
        elif best is not None:
            confidence = "low"
        else:
            confidence = "no match"

        match = {
            "reimb_id":            reimb.get("id", ""),
            "sufs_amount":         reimb.get("amount", ""),
            "sufs_provider":       reimb.get("provider", ""),
            "sufs_date":           r_date_raw,
            "sufs_student":        reimb.get("student", ""),
            "sufs_status":         reimb.get("status", ""),
            "num_line_items":      len(reimb.get("line_items", [])),
            "sheet_row_index":     best["row_index"] if best else None,
            "sheet_item":          best.get("item", "") if best else "",
            "sheet_store":         best.get("store", "") if best else "",
            "sheet_price":         best.get("price", "") if best else "",
            "sheet_order_number":  best.get("order_number", "") if best else "",
            "sheet_date_submitted":best.get("date_submitted", "") if best else "",
            "confidence":          confidence,
            "score":               round(best_score, 1),
        }
        matches.append(match)
        if best and confidence in ("high", "medium"):
            used_row_indices.add(best["row_index"])

    return matches

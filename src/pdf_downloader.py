"""
Downloads Amazon invoice PDFs via the existing CDP Chrome connection.
Saves to ~/Desktop/SUFS/2025-2026/<order_number>.pdf
"""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUTPUT_DIR = Path.home() / "Desktop" / "SUFS" / "2025-2026"
INVOICE_URL = "https://www.amazon.com/gp/css/summary/print.html?orderID={order_id}"


async def _download_one(order_id: str, cdp_port: int = 9222) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{order_id}.pdf"

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await ctx.new_page()
        await page.goto(INVOICE_URL.format(order_id=order_id), wait_until="networkidle")
        await page.wait_for_timeout(1500)
        await page.pdf(
            path=str(out_path),
            print_background=True,
            format="Letter",
        )
        await page.close()
        await browser.close()

    return str(out_path)


def download_invoices(order_ids: list, cdp_port: int = 9222) -> dict:
    """
    Download PDFs for a list of order IDs.
    Skips files that already exist on disk.
    Returns {order_id: file_path | "SKIPPED: already exists" | "ERROR: ..."}.
    Requires the SUFS Chrome window to be open (same CDP connection used for form filling).
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    for oid in order_ids:
        existing = OUTPUT_DIR / f"{oid}.pdf"
        if existing.exists():
            results[oid] = f"SKIPPED: {existing}"
            continue
        try:
            path = asyncio.run(_download_one(oid, cdp_port))
            results[oid] = path
        except Exception as e:
            results[oid] = f"ERROR: {e}"
    return results

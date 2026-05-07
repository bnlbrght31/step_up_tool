"""
Browser automation for filling SUFS reimbursement forms.

The SUFS form uses Bootstrap dropdowns (button + dropdown-menu with a.dropdown-item),
Radzen numeric inputs (rz-numeric-input), and standard HTML date/text inputs.

SETUP (one-time):
  Kill Chrome, then launch:
  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
      --remote-debugging-port=9222 \
      --user-data-dir="$HOME/.sufs-agent-chrome"
  Log in to SUFS, navigate to your reimbursement form, then run the app.
"""

import base64
import json
from pathlib import Path

import anthropic
from playwright.async_api import Browser, Page, async_playwright

from src.models import LineItem

_client = anthropic.Anthropic()
OPTIONS_FILE = Path("form_options.json")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MATCH_PROMPT = """\
Match this receipt value to the closest option in a form dropdown.
Receipt value: {extracted}
Available options:
{options}
Reply with ONLY the exact text of the best matching option."""


def _best_match_claude(extracted: str, options: list[str]) -> str:
    if not options:
        return ""
    if not extracted:
        return options[0]
    if extracted in options:
        return extracted
    msg = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=64,
        messages=[{"role": "user", "content": MATCH_PROMPT.format(
            extracted=extracted,
            options="\n".join(f"- {o}" for o in options),
        )}],
    )
    return msg.content[0].text.strip()


def _to_date_input(date_str: str | None) -> str:
    """Convert MM/DD/YYYY → YYYY-MM-DD for HTML date inputs."""
    if not date_str:
        return ""
    try:
        parts = date_str.replace("-", "/").split("/")
        if len(parts) == 3:
            if len(parts[2]) == 4:  # MM/DD/YYYY
                return f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
    except Exception:
        pass
    return date_str  # return as-is if already correct or unparseable


# ---------------------------------------------------------------------------
# Bootstrap dropdown helpers
# ---------------------------------------------------------------------------


async def _bs_options(btn_locator) -> list[str]:
    """Return non-placeholder option texts from a Bootstrap dropdown button."""
    return await btn_locator.evaluate("""btn => {
        const menu = btn.parentElement?.querySelector('.dropdown-menu');
        if (!menu) return [];
        return Array.from(menu.querySelectorAll('a.dropdown-item'))
            .map(a => a.textContent.trim())
            .filter(t => t && !/^select\\s/i.test(t));
    }""")


async def _bs_select(page: Page, btn_locator, value: str) -> str:
    """Open a Bootstrap dropdown and click the best-matching option."""
    options = await _bs_options(btn_locator)
    if not options:
        return ""
    choice = _best_match_claude(value, options)
    await btn_locator.click()
    await page.wait_for_timeout(350)
    await btn_locator.evaluate("""(btn, choice) => {
        const menu = btn.parentElement?.querySelector('.dropdown-menu');
        const item = Array.from(menu?.querySelectorAll('a.dropdown-item') || [])
            .find(a => a.textContent.trim() === choice);
        if (item) item.click();
    }""", choice)
    await page.wait_for_timeout(500)
    return choice


# ---------------------------------------------------------------------------
# Radzen numeric input helper
# ---------------------------------------------------------------------------


async def _rz_fill(input_locator, value: float | int):
    """Fill a Radzen numeric input (triple-click to select all, then fill)."""
    await input_locator.triple_click()
    await input_locator.fill(str(value))
    await input_locator.press("Tab")


# ---------------------------------------------------------------------------
# Vendor handling (Bootstrap dropdown + optional freeform)
# ---------------------------------------------------------------------------

NOT_LISTED_PHRASES = ["not listed", "not found", "other provider", "other"]


async def _handle_vendor(page: Page, vendor: str | None, index: int):
    """
    Select vendor from Bootstrap dropdown. Falls back to 'Provider not listed'
    + freeform input if the vendor isn't in the list.
    """
    # Try common IDs for the vendor dropdown
    vendor_btn = None
    for vid in ("vendor", "provider", "payee"):
        loc = page.locator(f"button#{vid}").nth(index)
        if await loc.count():
            vendor_btn = loc
            break

    if vendor_btn is None:
        # Fall back: find a Bootstrap dropdown button near "Who did you pay?" label
        vendor_btn = page.locator("button.dropdown-toggle.form-select").last

    if not vendor_btn or not await vendor_btn.count():
        return

    options = await _bs_options(vendor_btn)
    not_listed = next((o for o in options if any(p in o.lower() for p in NOT_LISTED_PHRASES)), None)
    choice = _best_match_claude(vendor or "", options)
    use_freeform = not_listed and (
        any(p in choice.lower() for p in NOT_LISTED_PHRASES) or choice not in options
    )

    if use_freeform and not_listed:
        await _bs_select(page, vendor_btn, not_listed)
        await page.wait_for_timeout(600)
        freeform = page.locator("input[placeholder*='provider' i], input[placeholder*='vendor' i], input[placeholder*='name' i]").last
        if await freeform.count():
            await freeform.fill(vendor or "")
    else:
        await _bs_select(page, vendor_btn, choice)


# ---------------------------------------------------------------------------
# CDP connection helper
# ---------------------------------------------------------------------------


async def _get_sufs_page(browser: Browser, form_url: str) -> Page:
    """Return the open SUFS reimbursement tab, or navigate to form_url."""
    all_sufs: list[Page] = []
    for context in browser.contexts:
        for pg in context.pages:
            if "stepupforstudents.org" in pg.url:
                all_sufs.append(pg)

    for pg in all_sufs:
        if "apply.stepupforstudents.org" in pg.url or "SubmitReimbursement" in pg.url:
            return pg
    if all_sufs:
        return all_sufs[0]

    if not form_url:
        raise RuntimeError("No SUFS tab found and no form_url provided. Open the form in Chrome first.")
    ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = await ctx.new_page()
    await page.goto(form_url)
    await page.wait_for_load_state("networkidle")
    return page


# ---------------------------------------------------------------------------
# Form inspection (for debugging selector issues)
# ---------------------------------------------------------------------------


async def inspect_form_elements(cdp_port: int = 9222) -> dict:
    async with async_playwright() as p:
        browser: Browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
        page = await _get_sufs_page(browser, "")

        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(800)

        result = await page.evaluate("""() => {
            // All Bootstrap dropdown buttons
            const bsDropdowns = Array.from(document.querySelectorAll('button[data-bs-toggle="dropdown"]')).map(btn => ({
                id: btn.id,
                className: btn.className.slice(0, 80),
                text: btn.textContent.trim().slice(0, 60),
                options: Array.from(btn.parentElement?.querySelectorAll('a.dropdown-item') || [])
                    .map(a => a.textContent.trim()).filter(t => t).slice(0, 8),
            }));

            // All inputs
            const inputs = Array.from(document.querySelectorAll('input')).map(el => ({
                type: el.type, id: el.id, placeholder: el.placeholder,
                className: el.className.slice(0, 60),
            }));

            // All labels
            const labels = Array.from(document.querySelectorAll('label')).map(el => ({
                text: el.textContent.trim().slice(0, 50),
                for: el.getAttribute('for') || '',
            }));

            // Add an Item button
            const addButtons = Array.from(document.querySelectorAll('button'))
                .filter(el => /add.*(item|expense)/i.test(el.textContent))
                .map(el => ({ id: el.id, className: el.className.slice(0,60), text: el.textContent.trim() }));

            return { url: location.href, bsDropdowns, inputs, labels, addButtons };
        }""")

        await page.screenshot(path="/tmp/sufs_form_inspect.png", full_page=True)
        await browser.close()
        return result


# ---------------------------------------------------------------------------
# Dropdown discovery (maps all category→type→description combos)
# ---------------------------------------------------------------------------


async def discover_form_options(form_url: str = "", cdp_port: int = 9222) -> dict:
    """Walk every category→type→description combination and save to form_options.json."""
    async with async_playwright() as p:
        browser: Browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
        page = await _get_sufs_page(browser, form_url)

        options_map: dict = {"categories": [], "types": {}, "descriptions": {}, "vendors": []}

        cat_btn = page.locator("button#category").first
        categories = await _bs_options(cat_btn)
        options_map["categories"] = categories

        for category in categories:
            await _bs_select(page, cat_btn, category)
            await page.wait_for_timeout(800)

            type_btn = page.locator("button#type").first
            if not await type_btn.count():
                options_map["types"][category] = []
                continue

            types = await _bs_options(type_btn)
            options_map["types"][category] = types

            for type_val in types:
                await _bs_select(page, type_btn, type_val)
                await page.wait_for_timeout(800)

                desc_btn = page.locator("button#description").first
                if await desc_btn.count():
                    descs = await _bs_options(desc_btn)
                    options_map["descriptions"][f"{category}|{type_val}"] = descs

        # Vendor options
        for vid in ("vendor", "provider", "payee"):
            loc = page.locator(f"button#{vid}").first
            if await loc.count():
                options_map["vendors"] = await _bs_options(loc)
                break

        OPTIONS_FILE.write_text(json.dumps(options_map, indent=2))
        await browser.close()
        return options_map


def load_form_options() -> dict | None:
    if OPTIONS_FILE.exists():
        return json.loads(OPTIONS_FILE.read_text())
    return None


# ---------------------------------------------------------------------------
# Fill a single line item
# ---------------------------------------------------------------------------


async def _click_add_item(page: Page):
    await page.get_by_role("button", name="Add an Item").click()
    await page.wait_for_timeout(1000)


async def _fill_item(page: Page, item: LineItem, index: int):
    """Fill one reimbursement line item."""
    if index > 0:
        prev_count = await page.locator("#purchaseDate").count()
        await _click_add_item(page)
        # Wait for the new row's date input to appear
        await page.wait_for_function(
            f"document.querySelectorAll('#purchaseDate').length > {prev_count}",
            timeout=5000,
        )

    # --- Purchase date ---
    if item.purchase_date:
        await page.locator("#purchaseDate").nth(index).fill(_to_date_input(item.purchase_date))

    # --- Category (Bootstrap dropdown) ---
    cat_btn = page.locator("button#category").nth(index)
    if item.category and await cat_btn.count():
        await _bs_select(page, cat_btn, item.category)
        # Wait for Type dropdown to appear (it's dynamic)
        try:
            await page.wait_for_function(
                f"document.querySelectorAll('button#type').length > {index}",
                timeout=3000,
            )
        except Exception:
            pass

    # --- Type ---
    type_btn = page.locator("button#type").nth(index)
    if item.type and await type_btn.count():
        await _bs_select(page, type_btn, item.type)
        try:
            await page.wait_for_function(
                f"document.querySelectorAll('button#description').length > {index}",
                timeout=3000,
            )
        except Exception:
            pass

    # --- Description ---
    desc_btn = page.locator("button#description").nth(index)
    if item.description and await desc_btn.count():
        await _bs_select(page, desc_btn, item.description)

    # --- Radzen numeric inputs ---
    if item.quantity is not None:
        await _rz_fill(page.locator('input[placeholder="Enter Quantity"]').nth(index), item.quantity)
    if item.cost is not None:
        await _rz_fill(page.locator('input[placeholder="Enter Cost per Item"]').nth(index), item.cost)
    if item.tax is not None:
        await _rz_fill(page.locator('input[placeholder="Enter Additional Costs"]').nth(index), item.tax)

    # --- Vendor ---
    await _handle_vendor(page, item.vendor, index)

    await page.wait_for_timeout(400)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def fill_form(form_url: str, items: list[LineItem], cdp_port: int = 9222):
    """Connect to existing Chrome via CDP and fill the reimbursement form."""
    async with async_playwright() as p:
        browser: Browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
        page = await _get_sufs_page(browser, form_url)

        for i, item in enumerate(items):
            await _fill_item(page, item, i)

        await page.bring_to_front()
        await browser.close()

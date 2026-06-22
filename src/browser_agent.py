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
    await page.wait_for_timeout(400)

    # dispatchEvent so Blazor's event system picks it up
    clicked = await btn_locator.evaluate("""(btn, choice) => {
        const menu = btn.parentElement?.querySelector('.dropdown-menu');
        const items = Array.from(menu?.querySelectorAll('a.dropdown-item') || []);
        const item = items.find(a => a.textContent.trim() === choice);
        if (!item) return false;
        item.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        return true;
    }""", choice)

    if not clicked:
        # Fuzzy fallback: case-insensitive substring match
        await btn_locator.evaluate("""(btn, choice) => {
            const menu = btn.parentElement?.querySelector('.dropdown-menu');
            const items = Array.from(menu?.querySelectorAll('a.dropdown-item') || []);
            const lc = choice.toLowerCase();
            const item = items.find(a => a.textContent.trim().toLowerCase().includes(lc));
            if (!item) return false;
            item.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            return true;
        }""", choice)

    await page.wait_for_timeout(500)
    return choice


# ---------------------------------------------------------------------------
# Radzen numeric input helper
# ---------------------------------------------------------------------------


async def _rz_fill(input_locator, value: float | int):
    """Fill a Radzen numeric input (select all, then fill)."""
    await input_locator.click(click_count=3)
    await input_locator.fill(str(value))
    await input_locator.press("Tab")


# ---------------------------------------------------------------------------
# Vendor handling (Bootstrap dropdown + optional freeform)
# ---------------------------------------------------------------------------

NOT_LISTED_PHRASES = ["not listed", "not found", "other provider", "other"]


async def _handle_vendor_btn(page: Page, vendor: str | None, vendor_btn):
    """Select vendor using the given Bootstrap dropdown button locator."""
    options = await _bs_options(vendor_btn)
    if not options:
        return

    not_listed = next((o for o in options if any(p in o.lower() for p in NOT_LISTED_PHRASES)), None)
    vendor_lower = (vendor or "").lower()

    substring_match = next((o for o in options if vendor_lower and vendor_lower in o.lower()), None)
    if not substring_match:
        substring_match = next((o for o in options if o.lower() in vendor_lower and len(o) > 3), None)

    if substring_match:
        await _bs_select(page, vendor_btn, substring_match)
    elif not_listed:
        # Snapshot existing text inputs so we can detect the newly revealed freeform field
        inputs_before = await page.evaluate("""() =>
            Array.from(document.querySelectorAll('input[type=text], input:not([type])'))
                .map(el => el.outerHTML.slice(0, 80))
        """)
        await _bs_select(page, vendor_btn, not_listed)
        await page.wait_for_timeout(800)

        # Find the input that wasn't there before
        new_input = await page.evaluate("""(before) => {
            const all = Array.from(document.querySelectorAll('input[type=text], input:not([type])'));
            const newEl = all.find(el => !before.includes(el.outerHTML.slice(0, 80)));
            if (newEl) { newEl.focus(); return true; }
            return false;
        }""", inputs_before)

        if new_input:
            # Fill whichever input now has focus
            await page.keyboard.type(vendor or "")
        else:
            # Fallback: named placeholder patterns
            freeform = page.locator(
                "input[placeholder*='provider' i], "
                "input[placeholder*='vendor' i], "
                "input[placeholder*='name' i]"
            ).last
            if await freeform.count():
                await freeform.clear()
                await freeform.fill(vendor or "")
    else:
        choice = _best_match_claude(vendor or "", options)
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
    """Fill one reimbursement line item.

    The SUFS form starts each row with [category, vendor]. Selecting a category
    inserts a type button between them: [category, type, vendor]. Selecting type
    inserts description: [category, type, description, vendor].

    We track positions via DOM element handles (not indices) so that repeated IDs
    across multiple items don't cause mis-targeting.
    """
    if index > 0:
        prev_count = await page.locator("#purchaseDate").count()
        await _click_add_item(page)
        await page.wait_for_function(
            f"document.querySelectorAll('#purchaseDate').length > {prev_count}",
            timeout=5000,
        )

    if item.purchase_date:
        await page.locator("#purchaseDate").nth(index).fill(_to_date_input(item.purchase_date))

    bs_btns = page.locator("button.dropdown-toggle.form-select")
    cat_btn = page.locator("button#category").nth(index)

    async def _next_btn_idx(anchor_el) -> int | None:
        """Index of the button immediately after anchor in the full bs-btn list."""
        return await page.evaluate("""(anchor) => {
            const all = Array.from(document.querySelectorAll('button.dropdown-toggle.form-select'));
            const idx = all.indexOf(anchor);
            return (idx >= 0 && idx + 1 < all.length) ? idx + 1 : null;
        }""", anchor_el)

    # --- Category ---
    count_before = await bs_btns.count()

    if item.category and await cat_btn.count():
        await _bs_select(page, cat_btn, item.category)
        try:
            await page.wait_for_function(
                f"document.querySelectorAll('button.dropdown-toggle.form-select').length > {count_before}",
                timeout=3000,
            )
        except Exception:
            pass

    # Get element handle AFTER category click (Blazor may re-render the button node)
    cat_el = await cat_btn.element_handle()

    # --- Type: button right after category in the DOM ---
    type_el = None
    if item.type and cat_el:
        type_idx = await _next_btn_idx(cat_el)
        if type_idx is not None:
            count_before_type = await bs_btns.count()
            await _bs_select(page, bs_btns.nth(type_idx), item.type)
            # Re-fetch element handle in case node was replaced during selection
            type_el = await bs_btns.nth(type_idx).element_handle()
            try:
                await page.wait_for_function(
                    f"document.querySelectorAll('button.dropdown-toggle.form-select').length > {count_before_type}",
                    timeout=3000,
                )
            except Exception:
                pass

    # --- Description: button right after type in the DOM ---
    desc_el = None
    if item.description and type_el:
        desc_idx = await _next_btn_idx(type_el)
        if desc_idx is not None:
            await _bs_select(page, bs_btns.nth(desc_idx), item.description)
            desc_el = await bs_btns.nth(desc_idx).element_handle()

    # --- Radzen numeric inputs ---
    if item.quantity is not None:
        await _rz_fill(page.locator('input[placeholder="Enter Quantity"]').nth(index), item.quantity)
    if item.cost is not None:
        await _rz_fill(page.locator('input[placeholder="Enter Cost per Item"]').nth(index), item.cost)
    if item.tax is not None:
        await _rz_fill(page.locator('input[placeholder="Enter Additional Costs"]').nth(index), item.tax)

    # --- Vendor: last button in this item's row ---
    # Each row ends with vendor, which is the last button before the next row's category button
    # (or last button overall for the last item). We find it using cat_el as the anchor.
    vendor_el = None
    if cat_el:
        vendor_idx = await page.evaluate("""(catEl) => {
            const all = Array.from(document.querySelectorAll('button.dropdown-toggle.form-select'));
            const catIdx = all.indexOf(catEl);
            if (catIdx < 0) return null;
            for (let i = catIdx + 1; i < all.length; i++) {
                if (all[i].id === 'category') return i - 1;
            }
            return all.length - 1;
        }""", cat_el)
        if vendor_idx is not None:
            await _handle_vendor_btn(page, item.vendor, bs_btns.nth(vendor_idx))
            vendor_el = await bs_btns.nth(vendor_idx).element_handle()

    await page.wait_for_timeout(400)

    # --- Read back what actually landed in the form (post-fill verification; no API) ---
    async def _txt(el):
        if not el:
            return None
        try:
            return (await el.evaluate("e => (e.textContent || '').trim()")) or None
        except Exception:
            return None

    async def _val(loc):
        try:
            return await loc.input_value()
        except Exception:
            return None

    return {
        "purchase_date": await _val(page.locator("#purchaseDate").nth(index)),
        "category": await _txt(cat_el),
        "type": await _txt(type_el),
        "description": await _txt(desc_el),
        "vendor": await _txt(vendor_el),
        "quantity": await _val(page.locator('input[placeholder="Enter Quantity"]').nth(index)),
        "cost": await _val(page.locator('input[placeholder="Enter Cost per Item"]').nth(index)),
        "tax": await _val(page.locator('input[placeholder="Enter Additional Costs"]').nth(index)),
    }


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


async def fill_form(form_url: str, items: list[LineItem], cdp_port: int = 9222):
    """Connect to existing Chrome via CDP and fill the reimbursement form."""
    async with async_playwright() as p:
        browser: Browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
        page = await _get_sufs_page(browser, form_url)

        readbacks = []
        for i, item in enumerate(items):
            readbacks.append(await _fill_item(page, item, i))

        await page.bring_to_front()
        await browser.close()
        return readbacks

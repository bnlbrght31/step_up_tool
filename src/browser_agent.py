"""
Browser automation for filling SUFS reimbursement forms.

Connects to an existing Chrome session via CDP, then fills each line item using
a combination of Playwright's label/role selectors and Claude vision as fallback.

SETUP (one-time):
  macOS: open -na "Google Chrome" --args --remote-debugging-port=9222
  Then log in to SUFS, navigate to your reimbursement form, and run the app.
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
# Dropdown helpers
# ---------------------------------------------------------------------------

MATCH_PROMPT = """\
You are matching a value extracted from a receipt to the closest option in a web form dropdown.

Extracted value: {extracted}

Available options:
{options}

Reply with ONLY the exact text of the best matching option — nothing else.
If nothing fits, pick the closest option anyway."""


async def _get_options(select_locator) -> list[str]:
    """Return non-placeholder option texts from a <select> element."""
    return await select_locator.evaluate(
        """el => Array.from(el.options)
             .map(o => o.text.trim())
             .filter(t => t && !['select...', '-- select --', 'select one', ''].includes(t.toLowerCase()))"""
    )


def _best_match_claude(extracted: str, options: list[str]) -> str:
    """Use Claude Haiku to pick the best matching option text."""
    if not options:
        return ""
    if not extracted:
        return options[0]
    if extracted in options:
        return extracted

    msg = _client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=64,
        messages=[
            {
                "role": "user",
                "content": MATCH_PROMPT.format(
                    extracted=extracted,
                    options="\n".join(f"- {o}" for o in options),
                ),
            }
        ],
    )
    return msg.content[0].text.strip()


async def _select_best(select_locator, extracted: str | None) -> str:
    """Select the best-matching option in a <select>; return the chosen text."""
    options = await _get_options(select_locator)
    if not options:
        return ""
    choice = _best_match_claude(extracted or "", options)
    await select_locator.select_option(label=choice)
    return choice


# ---------------------------------------------------------------------------
# Vendor handling
# ---------------------------------------------------------------------------

PROVIDER_NOT_LISTED_PHRASES = ["not listed", "not found", "other provider", "other"]


async def _handle_vendor(page: Page, vendor: str | None):
    """
    Select vendor from dropdown. Falls back to 'Provider not listed' + freeform
    entry if the vendor isn't in the list.
    """
    vendor_select = page.locator(
        "select[id*='vendor' i], select[name*='vendor' i], select[id*='provider' i]"
    ).first

    options = await _get_options(vendor_select)
    not_listed_options = [
        o for o in options if any(p in o.lower() for p in PROVIDER_NOT_LISTED_PHRASES)
    ]

    choice = _best_match_claude(vendor or "", options)
    use_freeform = (
        any(p in choice.lower() for p in PROVIDER_NOT_LISTED_PHRASES)
        or choice not in options
    )

    if use_freeform and not_listed_options:
        await vendor_select.select_option(label=not_listed_options[0])
        await page.wait_for_timeout(600)
        freeform = page.locator(
            "input[placeholder*='provider' i], input[placeholder*='vendor' i]"
        ).last
        await freeform.fill(vendor or "")
    else:
        await vendor_select.select_option(label=choice)


# ---------------------------------------------------------------------------
# Vision fallback — used when label-based selectors fail
# ---------------------------------------------------------------------------

VISION_PROMPT = """\
This is a screenshot of a web form. The user needs to fill in: {field}.
The current value to enter is: {value}

Identify the best element to interact with and return a JSON object:
{{
  "action": "fill" | "select" | "click",
  "selector": "<CSS selector>",
  "value": "<value to enter>"
}}
Return ONLY the JSON object."""


async def _vision_fallback(page: Page, field: str, value: str):
    """Take a screenshot and ask Claude vision how to fill a specific field."""
    screenshot = await page.screenshot()
    img_b64 = base64.standard_b64encode(screenshot).decode()

    msg = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
                    },
                    {"type": "text", "text": VISION_PROMPT.format(field=field, value=value)},
                ],
            }
        ],
    )

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    plan: dict = json.loads(raw)

    action = plan.get("action", "fill")
    selector = plan["selector"]
    val = plan.get("value", value)

    if action == "fill":
        await page.fill(selector, val)
    elif action == "select":
        await page.select_option(selector, label=val)
    elif action == "click":
        await page.click(selector)


# ---------------------------------------------------------------------------
# CDP connection helper
# ---------------------------------------------------------------------------


async def _get_sufs_page(browser: Browser, form_url: str) -> Page:
    """Return the open SUFS tab, or navigate to form_url in a new tab."""
    for context in browser.contexts:
        for pg in context.pages:
            if "stepupforstudents.org" in pg.url:
                return pg

    if not form_url:
        raise RuntimeError(
            "No SUFS tab found and no form_url provided. Open the form in Chrome first."
        )
    ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = await ctx.new_page()
    await page.goto(form_url)
    await page.wait_for_load_state("networkidle")
    return page


# ---------------------------------------------------------------------------
# Dropdown discovery
# ---------------------------------------------------------------------------


async def discover_form_options(form_url: str = "", cdp_port: int = 9222) -> dict:
    """
    Walk every category → type → description combination on the live form
    and save the results to form_options.json.
    """
    async with async_playwright() as p:
        browser: Browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
        page = await _get_sufs_page(browser, form_url)

        options_map: dict = {"categories": [], "types": {}, "descriptions": {}, "vendors": []}

        cat_sel = page.locator("select[id*='category' i], select[name*='category' i]").first
        type_sel = page.locator("select[id*='type' i], select[name*='type' i]").first
        desc_sel = page.locator(
            "select[id*='description' i], select[id*='desc' i], select[name*='description' i]"
        ).first
        vendor_sel = page.locator(
            "select[id*='vendor' i], select[name*='vendor' i], select[id*='provider' i]"
        ).first

        categories = await _get_options(cat_sel)
        options_map["categories"] = categories

        for category in categories:
            await cat_sel.select_option(label=category)
            await page.wait_for_timeout(800)

            types = await _get_options(type_sel)
            options_map["types"][category] = types

            for type_val in types:
                await type_sel.select_option(label=type_val)
                await page.wait_for_timeout(800)

                descriptions = await _get_options(desc_sel)
                options_map["descriptions"][f"{category}|{type_val}"] = descriptions

        options_map["vendors"] = await _get_options(vendor_sel)

        OPTIONS_FILE.write_text(json.dumps(options_map, indent=2))
        await browser.close()
        return options_map


def load_form_options() -> dict | None:
    """Load previously discovered form options, or None if not yet discovered."""
    if OPTIONS_FILE.exists():
        return json.loads(OPTIONS_FILE.read_text())
    return None


# ---------------------------------------------------------------------------
# Fill a single line item
# ---------------------------------------------------------------------------


async def _click_add_item(page: Page):
    candidates = [
        page.get_by_role("button", name="Add an Item"),
        page.get_by_role("link", name="Add an Item"),
        page.locator("button, a").filter(has_text="Add an Item"),
        page.locator("button, a").filter(has_text="Add Item"),
    ]
    for locator in candidates:
        if await locator.count() > 0:
            await locator.first.click()
            await page.wait_for_timeout(1000)
            return
    raise RuntimeError("Could not find 'Add an Item' button on the page.")


async def _fill_item(page: Page, item: LineItem, index: int):
    """Fill one reimbursement line item. index=0 means the first row is already open."""
    if index > 0:
        await _click_add_item(page)

    date_inputs = page.locator("input[type='date'], input[type='text'][placeholder*='date' i]")
    qty_inputs = page.locator(
        "input[placeholder*='quantity' i], input[id*='quantity' i], input[name*='quantity' i]"
    )
    cost_inputs = page.locator(
        "input[placeholder*='cost' i], input[id*='cost' i], input[name*='cost' i], input[placeholder*='amount' i]"
    )
    tax_inputs = page.locator(
        "input[placeholder*='tax' i], input[id*='tax' i], input[name*='tax' i]"
    )
    cat_selects = page.locator("select[id*='category' i], select[name*='category' i]")
    type_selects = page.locator("select[id*='type' i], select[name*='type' i]")
    desc_selects = page.locator(
        "select[id*='description' i], select[id*='desc' i], select[name*='description' i]"
    )

    async def safe_fill(locator_list, nth, value, field_name):
        try:
            if await locator_list.count() > nth:
                await locator_list.nth(nth).fill(str(value))
        except Exception:
            await _vision_fallback(page, field_name, str(value))

    async def safe_select(locator_list, nth, value, field_name):
        try:
            if await locator_list.count() > nth:
                await _select_best(locator_list.nth(nth), value)
        except Exception:
            await _vision_fallback(page, field_name, value or "")

    if item.purchase_date:
        await safe_fill(date_inputs, index, item.purchase_date, "Purchase Date")

    await safe_select(cat_selects, index, item.category, "Category")
    await page.wait_for_timeout(700)

    await safe_select(type_selects, index, item.type, "Type")
    await page.wait_for_timeout(700)

    await safe_select(desc_selects, index, item.description, "Description")

    if item.quantity is not None:
        await safe_fill(qty_inputs, index, item.quantity, "Quantity")
    if item.cost is not None:
        await safe_fill(cost_inputs, index, item.cost, "Cost")
    if item.tax is not None:
        await safe_fill(tax_inputs, index, item.tax, "Tax")

    try:
        await _handle_vendor(page, item.vendor)
    except Exception:
        await _vision_fallback(page, "Vendor", item.vendor or "")

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

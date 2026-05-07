"""
Browser automation for filling SUFS reimbursement forms.

Connects to an existing Chrome session via CDP, then fills each line item using
a combination of Playwright's label/role selectors and Claude vision as fallback.

SETUP (one-time):
  macOS: open -na "Google Chrome" --args --remote-debugging-port=9222
  Then log in to SUFS, navigate to your reimbursement form, and run the app.
"""

import asyncio
import base64
import json
import os

import anthropic
from playwright.async_api import Browser, Page, async_playwright

from src.models import LineItem

_client = anthropic.Anthropic()

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


async def _get_options(page: Page, select_locator) -> list[str]:
    """Return non-placeholder option texts from a <select> element."""
    return await select_locator.evaluate(
        """el => Array.from(el.options)
             .map(o => o.text.trim())
             .filter(t => t && !['select...', '-- select --', 'select one'].includes(t.toLowerCase()))"""
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


async def _select_best(page: Page, select_locator, extracted: str | None) -> str:
    """Select the best-matching option in a <select>; return the chosen text."""
    options = await _get_options(page, select_locator)
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
    Select vendor from dropdown. If vendor is not in the list (or Claude says
    to use the free-form fallback), choose the 'Provider not listed' option
    and type the vendor name into the text box that appears.
    """
    vendor_select = page.get_by_label("Vendor") or page.locator("select").filter(
        has_text="Provider"
    )

    options = await _get_options(page, vendor_select.first)
    not_listed_options = [
        o for o in options if any(p in o.lower() for p in PROVIDER_NOT_LISTED_PHRASES)
    ]

    choice = _best_match_claude(vendor or "", options)

    use_freeform = (
        any(p in choice.lower() for p in PROVIDER_NOT_LISTED_PHRASES)
        or choice not in options
    )

    if use_freeform and not_listed_options:
        await vendor_select.first.select_option(label=not_listed_options[0])
        await page.wait_for_timeout(600)
        freeform = page.get_by_placeholder("Provider Name") or page.locator(
            "input[type='text']:visible"
        ).last
        await freeform.fill(vendor or "")
    else:
        await vendor_select.first.select_option(label=choice)


# ---------------------------------------------------------------------------
# Vision fallback — used when label-based selectors fail
# ---------------------------------------------------------------------------

VISION_PROMPT = """\
This is a screenshot of a web form. The user needs to fill in: {field}.
The current value to enter is: {value}

Identify the best element to interact with and return a JSON object:
{{
  "action": "fill" | "select" | "click",
  "selector": "<CSS selector or descriptive text>",
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
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": VISION_PROMPT.format(field=field, value=value),
                    },
                ],
            }
        ],
    )

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    plan: dict = json.loads(raw)

    selector = plan["selector"]
    action = plan.get("action", "fill")
    val = plan.get("value", value)

    if action == "fill":
        await page.fill(selector, val)
    elif action == "select":
        await page.select_option(selector, label=val)
    elif action == "click":
        await page.click(selector)


# ---------------------------------------------------------------------------
# Fill a single line item
# ---------------------------------------------------------------------------


async def _click_add_item(page: Page):
    """Click the 'Add an Item' button and wait for the new section to appear."""
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
    """Fill one reimbursement line item. index=0 means the form is already open."""
    if index > 0:
        await _click_add_item(page)

    # Grab all instances of repeated fields (one per item row)
    date_inputs = page.locator("input[type='date'], input[type='text'][placeholder*='date' i]")
    qty_inputs = page.locator("input[placeholder*='quantity' i], input[id*='quantity' i], input[name*='quantity' i]")
    cost_inputs = page.locator("input[placeholder*='cost' i], input[id*='cost' i], input[name*='cost' i], input[placeholder*='amount' i]")
    tax_inputs = page.locator("input[placeholder*='tax' i], input[id*='tax' i], input[name*='tax' i]")
    cat_selects = page.locator("select[id*='category' i], select[name*='category' i]")
    type_selects = page.locator("select[id*='type' i], select[name*='type' i]")
    desc_selects = page.locator("select[id*='description' i], select[id*='desc' i], select[name*='description' i]")

    # --- Purchase date ---
    if item.purchase_date and await date_inputs.count() > index:
        try:
            await date_inputs.nth(index).fill(item.purchase_date)
        except Exception:
            await _vision_fallback(page, "Purchase Date", item.purchase_date)

    # --- Category (cascade root) ---
    if await cat_selects.count() > index:
        try:
            await _select_best(page, cat_selects.nth(index), item.category)
            await page.wait_for_timeout(700)  # let type dropdown populate
        except Exception:
            await _vision_fallback(page, "Category", item.category or "")

    # --- Type ---
    if await type_selects.count() > index:
        try:
            await _select_best(page, type_selects.nth(index), item.type)
            await page.wait_for_timeout(700)  # let description dropdown populate
        except Exception:
            await _vision_fallback(page, "Type", item.type or "")

    # --- Description ---
    if await desc_selects.count() > index:
        try:
            await _select_best(page, desc_selects.nth(index), item.description)
        except Exception:
            await _vision_fallback(page, "Description", item.description or "")

    # --- Quantity ---
    if item.quantity is not None and await qty_inputs.count() > index:
        try:
            await qty_inputs.nth(index).fill(str(item.quantity))
        except Exception:
            await _vision_fallback(page, "Quantity", str(item.quantity))

    # --- Cost ---
    if item.cost is not None and await cost_inputs.count() > index:
        try:
            await cost_inputs.nth(index).fill(str(item.cost))
        except Exception:
            await _vision_fallback(page, "Cost", str(item.cost))

    # --- Tax ---
    if item.tax is not None and await tax_inputs.count() > index:
        try:
            await tax_inputs.nth(index).fill(str(item.tax))
        except Exception:
            await _vision_fallback(page, "Tax", str(item.tax))

    # --- Vendor ---
    try:
        await _handle_vendor(page, item.vendor)
    except Exception:
        await _vision_fallback(page, "Vendor", item.vendor or "")

    await page.wait_for_timeout(400)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def fill_form(form_url: str, items: list[LineItem], cdp_port: int = 9222):
    """
    Connect to an existing Chrome session via CDP and fill the reimbursement form.

    Preconditions:
    - Chrome launched with: open -na "Google Chrome" --args --remote-debugging-port=9222
    - User is logged in to SUFS with the reimbursement form already open.
    """
    async with async_playwright() as p:
        browser: Browser = await p.chromium.connect_over_cdp(
            f"http://localhost:{cdp_port}"
        )

        # Find the SUFS tab
        page: Page | None = None
        for context in browser.contexts:
            for pg in context.pages:
                if "stepupforstudents.org" in pg.url:
                    page = pg
                    break
            if page:
                break

        if page is None:
            if not form_url:
                raise RuntimeError(
                    "No SUFS tab found and no form_url provided. "
                    "Open the form in Chrome first."
                )
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await ctx.new_page()
            await page.goto(form_url)
            await page.wait_for_load_state("networkidle")

        for i, item in enumerate(items):
            await _fill_item(page, item, i)

        # Bring the tab to the foreground so the user can review
        await page.bring_to_front()

import base64
import json
import math
import re
from pathlib import Path

import anthropic

from src.models import LineItem

client = anthropic.Anthropic()

PRICING = {
    "claude-sonnet-4-6":       (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80,  4.00),
}

def _print_cost(model: str, usage, label: str = ""):
    input_price, output_price = PRICING.get(model, (3.00, 15.00))
    cost = (usage.input_tokens * input_price + usage.output_tokens * output_price) / 1_000_000
    tag = f"[{label}] " if label else ""
    print(f"{tag}API cost: ${cost:.4f}  ({usage.input_tokens:,} in / {usage.output_tokens:,} out)")

_GUIDE_PATH = Path(__file__).parent.parent / "docs" / "purchasing_guide_reference.md"

EXTRACTION_PROMPT_TEMPLATE = """You are a receipt parser for the Step Up For Students scholarship reimbursement program in Florida.

Use the purchasing guide reference below to assign the correct category and type to each item.

--- PURCHASING GUIDE REFERENCE ---
{guide}
--- END REFERENCE ---

Extract EVERY line item from this receipt exactly as it appears — do not filter, skip, or comment on any items. For each item return:
- purchase_date: date of purchase as MM/DD/YYYY (use the receipt date if per-item date is absent)
- category: the top-level category from the purchasing guide (e.g. "Instructional Materials", "Tuition & Fees", "Part-Time Tutoring & Choice Navigator Services")
- type: the sub-type within that category (e.g. "Books", "Learning Manipulatives & Creative Play Items", "Physical Education (P.E.)", "At-Home Classroom Furnishings")
- description: a short, plain-English description of the item
- quantity: numeric quantity purchased
- cost: the line item's total cost BEFORE tax (for the full quantity), as a number with no $ sign
- vendor: store or company name

Do NOT compute or distribute tax per item. Instead, return the receipt's totals exactly as printed so the app can distribute tax itself:
- subtotal: the pre-tax subtotal (sum of all item costs), or null if the receipt doesn't show one
- tax: the single total sales tax amount on the receipt, or null if there is none
- grand_total: the final amount charged (subtotal + tax), or null if not shown

Return ONLY a valid JSON object with no markdown fences, no explanation, no other text. Example:
{{
  "items": [
    {{
      "purchase_date": "03/12/2025",
      "category": "Instructional Materials",
      "type": "Books",
      "description": "Grade 5 Math Workbook",
      "quantity": 1,
      "cost": 18.99,
      "vendor": "Barnes & Noble"
    }}
  ],
  "totals": {{ "subtotal": 18.99, "tax": 1.33, "grand_total": 20.32 }}
}}

If a field cannot be determined, use null."""


def _build_prompt() -> str:
    guide = _GUIDE_PATH.read_text() if _GUIDE_PATH.exists() else ""
    return EXTRACTION_PROMPT_TEMPLATE.format(guide=guide)


def _num(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _distribute_tax(items: list[LineItem], tax_total: float | None):
    """Spread the receipt's total tax across items in proportion to cost, in whole
    cents, so the per-item taxes sum back to exactly tax_total."""
    costs = [float(it.cost or 0) for it in items]
    if not tax_total or tax_total <= 0 or sum(costs) <= 0:
        for it in items:
            it.tax = 0.0
        return
    total = sum(costs)
    raw = [tax_total * c / total for c in costs]
    cents = [int(math.floor(r * 100)) for r in raw]
    remainder = int(round(tax_total * 100)) - sum(cents)
    # hand the leftover cents to the items with the largest fractional parts
    order = sorted(range(len(items)), key=lambda i: (raw[i] * 100 - cents[i]), reverse=True)
    for k in range(max(remainder, 0)):
        cents[order[k % len(order)]] += 1
    for it, c in zip(items, cents):
        it.tax = round(c / 100, 2)


def _reconcile(items: list[LineItem], totals: dict) -> dict:
    """Distribute tax (Python-side) and compare the computed subtotal/total
    against the receipt's printed totals so the UI can flag any divergence."""
    subtotal = _num(totals.get("subtotal"))
    tax_total = _num(totals.get("tax"))
    grand = _num(totals.get("grand_total"))

    _distribute_tax(items, tax_total)

    items_subtotal = round(sum(float(it.cost or 0) for it in items), 2)
    tax_distributed = round(sum(float(it.tax or 0) for it in items), 2)
    computed_total = round(items_subtotal + tax_distributed, 2)

    def _ok(a, b):
        return a is None or b is None or abs(a - b) <= 0.02

    return {
        "subtotal": subtotal,
        "tax": tax_total,
        "grand_total": grand,
        "items_subtotal": items_subtotal,
        "tax_distributed": tax_distributed,
        "computed_total": computed_total,
        "subtotal_ok": _ok(items_subtotal, subtotal),
        "total_ok": _ok(computed_total, grand),
        "has_totals": any(v is not None for v in (subtotal, tax_total, grand)),
    }


def parse_receipt(pdf_path: str) -> tuple[list[LineItem], float, dict]:
    """Parse a receipt PDF with Claude.

    Returns (items, parse_cost, reconciliation). Tax is distributed across items
    in Python from the receipt's single total-tax figure (not by the LLM), and
    the reconciliation compares the computed subtotal/total to the receipt's.
    """
    pdf_bytes = Path(pdf_path).read_bytes()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": _build_prompt()},
                ],
            }
        ],
    )

    input_tokens, output_tokens = message.usage.input_tokens, message.usage.output_tokens
    parse_cost = (input_tokens * 3.00 + output_tokens * 15.00) / 1_000_000
    _print_cost("claude-sonnet-4-6", message.usage, "receipt parser")
    raw = message.content[0].text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Find the JSON payload — a {"items":[...], "totals":{...}} object, or a bare
    # array for backward-compat with the old format.
    if not (raw.startswith("{") or raw.startswith("[")):
        match = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON found in model response:\n{raw[:500]}")
        raw = match.group(0)

    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        items_data = parsed.get("items", [])
        totals = parsed.get("totals") or {}
    else:                       # bare array (older format) — no receipt totals
        items_data, totals = parsed, {}

    items = [LineItem.from_dict(item) for item in items_data]
    reconciliation = _reconcile(items, totals)
    return items, parse_cost, reconciliation

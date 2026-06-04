import base64
import json
import re
from pathlib import Path

import anthropic

from src.models import LineItem

client = anthropic.Anthropic()

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
- cost: unit cost as a number (no $ sign)
- tax: tax amount for this item as a number (no $ sign, 0 if none). If the receipt only shows a total tax (not per-item), distribute it proportionally across items based on each item's cost relative to the subtotal. Round to 2 decimal places.
- vendor: store or company name

Return ONLY a valid JSON array with no markdown fences, no explanation, no other text. Example:
[
  {{
    "purchase_date": "03/12/2025",
    "category": "Instructional Materials",
    "type": "Books",
    "description": "Grade 5 Math Workbook",
    "quantity": 1,
    "cost": 18.99,
    "tax": 1.33,
    "vendor": "Barnes & Noble"
  }}
]

If a field cannot be determined, use null."""


def _build_prompt() -> str:
    guide = _GUIDE_PATH.read_text() if _GUIDE_PATH.exists() else ""
    return EXTRACTION_PROMPT_TEMPLATE.format(guide=guide)


def parse_receipt(pdf_path: str) -> list[LineItem]:
    """Parse a receipt PDF with Claude and return structured line items."""
    pdf_bytes = Path(pdf_path).read_bytes()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
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

    raw = message.content[0].text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # If response isn't a bare JSON array, find the array within it
    if not raw.startswith("["):
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON array found in model response:\n{raw[:500]}")
        raw = match.group(0)

    items_data: list[dict] = json.loads(raw)
    return [LineItem.from_dict(item) for item in items_data]

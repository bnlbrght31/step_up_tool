import base64
import json
import re
from pathlib import Path

import anthropic

from src.models import LineItem

client = anthropic.Anthropic()

EXTRACTION_PROMPT = """You are a receipt parser for a school reimbursement program.

Extract EVERY line item from this receipt exactly as it appears — do not filter, skip, or comment on any items. For each item return:
- purchase_date: date of purchase as MM/DD/YYYY (use the receipt date if per-item date is absent)
- category: the general category (e.g. "Educational Materials", "Technology", "Tutoring", "Uniforms")
- type: the sub-type within that category (e.g. "Books", "Software", "Online Tutoring")
- description: a short, plain-English description of the item
- quantity: numeric quantity purchased
- cost: unit cost as a number (no $ sign)
- tax: tax amount for this item as a number (no $ sign, 0 if none)
- vendor: store or company name

Return ONLY a valid JSON array with no markdown fences, no explanation, no other text. Example:
[
  {
    "purchase_date": "03/12/2025",
    "category": "Educational Materials",
    "type": "Books",
    "description": "Grade 5 Math Workbook",
    "quantity": 1,
    "cost": 18.99,
    "tax": 1.33,
    "vendor": "Barnes & Noble"
  }
]

If a field cannot be determined, use null."""


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
                    {"type": "text", "text": EXTRACTION_PROMPT},
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

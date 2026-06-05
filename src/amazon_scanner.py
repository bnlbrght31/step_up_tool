"""
Amazon order scanner for SUFS reimbursement tracking.

Scans Gmail for Amazon order confirmation emails since the last scan date
(defaults to scholarship year start: 07/01/2025). Checks eligibility via
keyword matching against the SUFS purchasing guide — no API cost.
"""

import json
import re
from datetime import datetime
from pathlib import Path

SCAN_STATE_FILE = Path("scan_state.json")
SCHOLARSHIP_START = "2025/07/01"

GMAIL_TOKEN_FILE = "token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# ---------------------------------------------------------------------------
# Eligibility keyword matching
# ---------------------------------------------------------------------------

ELIGIBILITY_MAP = {
    "Books": [
        "book", "workbook", "textbook", "novel", "reader", "curriculum",
        "guide", "journal", "bible", "scripture", "story", "literature",
        "read aloud", "read-aloud", "phonics", "spelling", "grammar",
        "history", "geography", "science", "math", "language arts",
        # Common educational book series/title words
        "lessons", "level ", "the lesson", "language lesson",
        "explode the code", "national geographic", "national ggeographic",
        # Spanish-title books common in SUFS
        "veo", "soy un", "el dios", "sonadores", "biblioburro",
        "cerdita", "llamitas", "que fue",
    ],
    "School Supplies": [
        "backpack", "notebook", "folder", "binder", "pencil", "pen",
        "crayon", "marker", "calculator", "scissors", "ruler", "stapler",
        "eraser", "planner", "lunchbox", "ink cartridge", "toner",
        "highlighter", "compass", "protractor", "abacus",
        "fastener", "paper clip", "paperclip",
    ],
    "Learning Manipulatives & Creative Play Items": [
        "lego", "puzzle", "board game", "game board", "blocks", "chess",
        "domino", "stuffed animal", "stuffi", "stuffies", "magna tile",
        "magnatile", "flashcard", "flash card", "manipulative",
        "play kitchen", "water table", "dress-up", "doll", "marble",
        "card game", "wooden toy", "wood toy", "montessori",
        "stacking toy", "sorting toy", "nesting", "stacking",
        "melissa and doug", "dino", "dinosaur toy", "wooden food",
        "wooden puzzle", "wooden stamp", "montossori", "pepa pig",
        "cube", "toy:", "game-", "game –",
    ],
    "Physical Education": [
        "ball", "bike", "bicycle", "skateboard", "scooter", "sport",
        "athletic", "dance", "swim", "kayak", "racquet", "goal net",
        "soccer net", "basketball hoop", "helmet", "shin guard",
        "cleats", "uniform", "boogie board", "body board", "surfboard",
        "paddleboard", "trampoline", "treadmill", "stationary bike",
        "weight bench", "knee pad", "elbow pad",
    ],
    "Musical Instruments & Equipment": [
        "instrument", "guitar", "piano", "violin", "drum", "flute",
        "keyboard", "trumpet", "ukulele", "recorder", "microphone",
        "music stand",
    ],
    "At-Home Classroom Furnishings": [
        "desk", "chair", "whiteboard", "white board", "chalkboard",
        "chalk board", "bookshelf", "bookcase", "globe", "atlas", "map",
        "projector", "clock", "timer", "bulletin board", "rug", "carpet",
        "easel", "drafting table",
    ],
    "Electives": [
        "art supply", "art supplies", "paint", "paintbrush", "canvas",
        "clay", "cooking", "baking", "sewing", "knitting", "woodworking",
        "gardening", "seed", "soil", "photography", "drama",
        "craft supply", "craft supplies", "felt", "sand art",
    ],
    "Sensory Materials": [
        "sensory", "fidget", "weighted blanket", "weighted vest",
        "balance ball", "therapy chair", "lava lamp", "bubble tube",
        "air walker",
    ],
    "Digital Materials": [
        "ebook", "audiobook", "dvd", "educational app", "cd-rom",
        "yoto",
    ],
    "Internet Resources": [
        "internet service", "wifi", "wi-fi", "hotspot", "modem", "router",
    ],
    "Field Trips & Other Activities": [
        "zoo", "museum", "aquarium", "theme park", "admission",
        "membership", "legoland", "disney", "universal studios",
        "seaworld", "busch gardens",
    ],
    "Lab Fees & Materials": [
        "microscope", "science kit", "lab supply", "chemistry set",
        "biology", "experiment kit",
    ],
}


def check_eligibility(description: str) -> str | None:
    """Return the best-matching SUFS category or None. Keyword-only fallback."""
    text = description.lower()
    for category, keywords in ELIGIBILITY_MAP.items():
        if any(kw in text for kw in keywords):
            return category
    return None


def batch_check_eligibility(descriptions: list) -> list:
    """
    Check eligibility for a list of item descriptions in one Claude Haiku call.
    Returns a list of category strings (or None) in the same order as input.
    Falls back to keyword matching if the API call fails.
    """
    if not descriptions:
        return []

    from pathlib import Path
    import anthropic
    import json as _json

    guide_path = Path(__file__).parent.parent / "docs" / "purchasing_guide_reference.md"
    guide = guide_path.read_text() if guide_path.exists() else ""
    client = anthropic.Anthropic()
    total_in = total_out = 0

    def _call_claude(chunk: list) -> list:
        nonlocal total_in, total_out
        # Send as JSON array so special characters (quotes, slashes) don't confuse parsing.
        # Ask for a JSON object keyed by index so a missing entry doesn't shift all results.
        items_json = _json.dumps(chunk)
        prompt = f"""You are checking whether Amazon purchase descriptions are eligible for the Step Up For Students (SUFS) scholarship reimbursement program in Florida.

Use the purchasing guide below to decide eligibility.

--- PURCHASING GUIDE ---
{guide}
--- END GUIDE ---

Below is a JSON array of Amazon item descriptions (0-indexed). For each index return the top-level SUFS category if eligible, or null if not eligible (e.g. personal clothing, adult items, household goods unrelated to education).

Items:
{items_json}

Return ONLY a valid JSON object mapping each index (as a string) to a category string or null. Example:
{{"0": "Books", "1": null, "2": "Physical Education"}}

No explanation, no markdown."""

        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        result_map = _json.loads(raw)
        total_in += msg.usage.input_tokens
        total_out += msg.usage.output_tokens
        # Build list in order, falling back to keyword match for any missing index
        return [result_map.get(str(i)) or check_eligibility(chunk[i]) for i in range(len(chunk))]

    CHUNK_SIZE = 50
    all_results = []
    for i in range(0, len(descriptions), CHUNK_SIZE):
        chunk = [d.replace("\n", " ").replace("\r", " ") for d in descriptions[i:i + CHUNK_SIZE]]
        try:
            all_results.extend(_call_claude(chunk))
        except Exception as e:
            print(f"[scanner] Claude chunk {i//CHUNK_SIZE + 1} failed ({e}), using keywords for this chunk")
            all_results.extend([check_eligibility(d) for d in chunk])

    eligibility_cost = 0.0
    if total_in or total_out:
        eligibility_cost = (total_in * 0.80 + total_out * 4.00) / 1_000_000
        print(f"[eligibility check] API cost: ${eligibility_cost:.4f}  ({total_in:,} in / {total_out:,} out)")

    return all_results, eligibility_cost


# ---------------------------------------------------------------------------
# Scan state (last scan date persistence)
# ---------------------------------------------------------------------------

def load_last_scan() -> str:
    """Return Gmail after: date string (YYYY/MM/DD). Defaults to scholarship start."""
    if SCAN_STATE_FILE.exists():
        try:
            state = json.loads(SCAN_STATE_FILE.read_text())
            return state.get("last_scan_date", SCHOLARSHIP_START)
        except Exception:
            pass
    return SCHOLARSHIP_START


def save_last_scan():
    """Save today as the last scan date."""
    today = datetime.now().strftime("%Y/%m/%d")
    SCAN_STATE_FILE.write_text(json.dumps({"last_scan_date": today}, indent=2))


# ---------------------------------------------------------------------------
# Gmail helpers
# ---------------------------------------------------------------------------

def _get_gmail_service():
    import os
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_path = os.environ.get("GMAIL_TOKEN_FILE", GMAIL_TOKEN_FILE)
    if not Path(token_path).exists():
        raise RuntimeError(
            "Gmail not authorized. Copy token.json from the pickem app, "
            "or run: python authorize_gmail.py"
        )
    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        Path(token_path).write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def _get_header(msg, name: str) -> str:
    headers = msg.get("payload", {}).get("headers", [])
    return next((h["value"] for h in headers if h["name"].lower() == name.lower()), "")


def _decode_body(msg) -> str:
    """Decode email body to plain text, stripping HTML tags if needed."""
    import base64

    def _extract(payload):
        mime = payload.get("mimeType", "")
        data = payload.get("body", {}).get("data", "")
        if mime == "text/plain" and data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        if mime == "text/html" and data:
            html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            return re.sub(r"<[^>]+>", " ", html)
        for part in payload.get("parts", []):
            result = _extract(part)
            if result:
                return result
        return ""

    return _extract(msg.get("payload", {}))


# ---------------------------------------------------------------------------
# Order email parsing
# ---------------------------------------------------------------------------

ORDER_RE = re.compile(r"\b(\d{3}-\d{7}-\d{7})\b")
# Amazon puts total on the next line: "Grand Total:\n12.34 USD"
# Also handle inline: "Grand Total: $12.34"
TOTAL_RE = re.compile(
    r"(?:order total|grand total)\s*:?\s*\n?\s*\$?([\d,]+\.\d{2})\s*(?:USD)?",
    re.IGNORECASE,
)


def _parse_order_email(msg) -> dict | None:
    """Extract order number, date, description, and total from one Amazon email."""
    from email.utils import parsedate_to_datetime

    subject = _get_header(msg, "Subject")
    date_header = _get_header(msg, "Date")
    body = _decode_body(msg)
    full_text = f"{subject}\n{body}"

    # Order number is required
    match = ORDER_RE.search(full_text)
    if not match:
        return None
    order_number = match.group(1)

    # Purchase date from email Date header
    try:
        dt = parsedate_to_datetime(date_header)
        purchase_date = dt.strftime("%Y-%m-%d")
    except Exception:
        purchase_date = ""

    # Description from subject line
    # Amazon subjects: 'Ordered: "Item name..."' or 'Your Amazon.com order of X'
    ordered_match = re.match(r'^Ordered:\s*"(.+?)"', subject)
    if ordered_match:
        description = ordered_match.group(1).strip()
    else:
        desc_match = re.search(
            r"order of (.+?)(?:\s+has been|\s+has shipped|\s+is on|\s+will arrive|$)",
            subject, re.IGNORECASE,
        )
        if desc_match:
            description = desc_match.group(1).strip()
        else:
            description = re.sub(
                r"(?:your\s+)?amazon\.?com\s+order\s*(?:of\s+|#\s*\S+\s*)?",
                "", subject, flags=re.IGNORECASE,
            ).strip() or "Amazon order"

    # Total
    total = ""
    m = TOTAL_RE.search(full_text)
    if m:
        total = m.group(1).replace(",", "")

    return {
        "order_number": order_number,
        "purchase_date": purchase_date,
        "description": description,
        "total": total,
        "eligible_category": check_eligibility(description),
    }


# ---------------------------------------------------------------------------
# Main scan entry point
# ---------------------------------------------------------------------------

def scan_amazon_orders(existing_order_numbers: set, from_date: str | None = None) -> tuple[list, str]:
    """
    Search Gmail for Amazon order confirmations since from_date (YYYY-MM-DD),
    or the last scan date, or the scholarship year start if neither is set.

    Returns (orders, after_date_used).
    Each order dict has: order_number, purchase_date, description,
    total, eligible_category, in_sheet (bool).
    Deduplicates within the scan and against existing_order_numbers.
    """
    if from_date:
        # Convert YYYY-MM-DD → YYYY/MM/DD for Gmail query
        after_date = from_date.replace("-", "/")
    else:
        after_date = load_last_scan()
    query = f'from:auto-confirm@amazon.com after:{after_date}'

    service = _get_gmail_service()
    results = service.users().messages().list(
        userId="me", q=query, maxResults=500
    ).execute()
    messages = results.get("messages", [])

    orders = []
    seen = set()

    for msg_ref in messages:
        try:
            msg = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="full"
            ).execute()
            parsed = _parse_order_email(msg)
            if not parsed:
                continue
            on = parsed["order_number"]
            if on in seen:
                continue
            seen.add(on)
            parsed["in_sheet"] = on in existing_order_numbers
            orders.append(parsed)
        except Exception as e:
            print(f"[scanner] Error processing message: {e}")

    orders.sort(key=lambda o: o.get("purchase_date", ""))

    # Batch eligibility check via Claude Haiku (one API call for all orders)
    descriptions = [o["description"] for o in orders]
    categories, eligibility_cost = batch_check_eligibility(descriptions)
    for order, category in zip(orders, categories):
        order["eligible_category"] = category

    return orders, after_date, eligibility_cost

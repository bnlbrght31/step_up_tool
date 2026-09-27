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

from src import scholarship_year
from src.gmail import list_message_stubs

SCAN_STATE_FILE = Path("scan_state.json")
# Start of the current scholarship year; the default "scan from" date when no
# prior scan state exists.
SCHOLARSHIP_START = scholarship_year.gmail_date(scholarship_year.start_year())

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
    total_cache_write = total_cache_read = 0

    # The guide is identical for every chunk, so it goes in a cached system block
    # ahead of the per-chunk items. A scan sends it once at 1.25x and every later
    # chunk reads it at 0.1x instead of resending ~5.6k tokens each time.
    system = [
        {
            "type": "text",
            "text": f"""You are checking whether Amazon purchase descriptions are eligible for the Step Up For Students (SUFS) scholarship reimbursement program in Florida.

Use the purchasing guide below to decide eligibility.

--- PURCHASING GUIDE ---
{guide}
--- END GUIDE ---""",
            "cache_control": {"type": "ephemeral"},
        }
    ]

    def _call_claude(chunk: list) -> list:
        nonlocal total_in, total_out, total_cache_write, total_cache_read
        # Send as JSON array so special characters (quotes, slashes) don't confuse parsing.
        # Ask for a JSON object keyed by index so a missing entry doesn't shift all results.
        items_json = _json.dumps(chunk)
        prompt = f"""Below is a JSON array of Amazon item descriptions (0-indexed). For each index return the top-level SUFS category if eligible, or null if not eligible (e.g. personal clothing, adult items, household goods unrelated to education).

Items:
{items_json}

Return ONLY a valid JSON object mapping each index (as a string) to a category string or null. Example:
{{"0": "Books", "1": null, "2": "Physical Education"}}

No explanation, no markdown."""

        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=system,
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
        total_cache_write += getattr(msg.usage, "cache_creation_input_tokens", 0) or 0
        total_cache_read += getattr(msg.usage, "cache_read_input_tokens", 0) or 0
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
    if total_in or total_out or total_cache_write or total_cache_read:
        # Cache writes bill at 1.25x the input rate, reads at 0.1x; neither is
        # included in input_tokens.
        eligibility_cost = (
            total_in * 0.80
            + total_cache_write * 0.80 * 1.25
            + total_cache_read * 0.80 * 0.10
            + total_out * 4.00
        ) / 1_000_000
        cache = ""
        if total_cache_write or total_cache_read:
            cache = f", {total_cache_write:,} cache-write / {total_cache_read:,} cache-read"
        print(f"[eligibility check] API cost: ${eligibility_cost:.4f}  ({total_in:,} in / {total_out:,} out{cache})")

    return all_results, eligibility_cost


# ---------------------------------------------------------------------------
# Return email scanning
# ---------------------------------------------------------------------------

_RETURN_SUBJECT_PREFIXES = [
    "Return request confirmed for ",
    "Your return drop off confirmation for ",
    "Your refund for ",
    "Advance refund issued for ",
    "Partial refund confirmed for ",
]

def _parse_return_subject(subject: str) -> str | None:
    """Extract the returned item name from an Amazon return email subject."""
    for prefix in _RETURN_SUBJECT_PREFIXES:
        if subject.lower().startswith(prefix.lower()):
            return subject[len(prefix):].rstrip(". ")
    return None


def scan_return_emails(after_date: str) -> dict:
    """
    Scan Gmail for Amazon return/refund emails since after_date.
    Returns {order_number: {"items": [str], "partial": bool}}
    """
    service = _get_gmail_service()
    queries = [
        f"from:return@amazon.com after:{after_date}",
        f"from:payments-messages@amazon.com after:{after_date} subject:refund",
    ]
    returns: dict = {}

    for query in queries:
        for ref in list_message_stubs(service, query):
            try:
                msg = service.users().messages().get(
                    userId="me", id=ref["id"], format="full"
                ).execute()
                subject = _get_header(msg, "Subject")
                body = _decode_body(msg)
                order_numbers = ORDER_RE.findall(f"{subject}\n{body}")
                if not order_numbers:
                    continue
                order_number = order_numbers[0]
                is_partial = "partial refund" in subject.lower()
                item_name = _parse_return_subject(subject)
                if order_number not in returns:
                    returns[order_number] = {"items": set(), "partial": is_partial}
                if item_name:
                    returns[order_number]["items"].add(item_name)
                if is_partial:
                    returns[order_number]["partial"] = True
            except Exception as e:
                print(f"[scanner] Error processing return email: {e}")

    return {on: {"items": list(d["items"]), "partial": d["partial"]} for on, d in returns.items()}


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
    print(f"[scanner] Scan date updated to {today}")


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
    messages = list_message_stubs(service, query)

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

    # Annotate orders with return/refund info
    print("[scanner] Scanning for return emails…")
    return_data = scan_return_emails(after_date)
    print(f"[scanner] Found {len(return_data)} order(s) with returns")
    for order in orders:
        on = order["order_number"]
        if on in return_data:
            order["has_return"] = True
            order["returned_items"] = return_data[on]["items"]
            order["partial_return"] = return_data[on]["partial"]
        else:
            order["has_return"] = False
            order["returned_items"] = []
            order["partial_return"] = False

    return orders, after_date, eligibility_cost

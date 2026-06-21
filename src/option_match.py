"""
Snap parsed receipt labels to the actual SUFS form dropdown options.

The receipt parser emits free-text category/type/description/vendor labels from
the purchasing guide, but the form only accepts its own discovered options
(form_options.json). This module fuzzy-matches each parsed label to the nearest
valid option and reports a confidence so the confirm page can pre-select the
right option and badge low-confidence matches for a human check.

Pure-Python (difflib) — no network, runs at confirm time.
"""

from difflib import SequenceMatcher


def _best(value: str | None, options: list[str]):
    """Return (best_option, ratio). ratio is None when there are no options."""
    if not options:
        return None, None
    if not value:
        return None, 0.0
    v = value.strip().lower()
    for o in options:                       # exact (case-insensitive)
        if o.strip().lower() == v:
            return o, 1.0
    best_o, best_r = None, 0.0
    for o in options:
        ol = o.strip().lower()
        r = SequenceMatcher(None, v, ol).ratio()
        if v in ol or ol in v:              # substring counts as a strong match
            r = max(r, 0.9)
        if r > best_r:
            best_o, best_r = o, round(r, 3)
    return best_o, best_r


# Below this similarity we keep the extracted text rather than snap to a likely
# wrong option (e.g. vendor "amazn" should not become some unrelated provider).
SNAP_THRESHOLD = 0.6


def _label(ratio) -> str:
    if ratio is None:
        return "none"        # nothing to match against — no badge
    if ratio >= 0.95:
        return "high"
    if ratio >= 0.75:
        return "medium"
    return "low"


def _field(raw, snapped, ratio) -> dict:
    use_snap = bool(snapped) and ratio is not None and ratio >= SNAP_THRESHOLD
    return {
        "raw": raw,
        "value": snapped if use_snap else raw,  # what the dropdown should pre-select
        "confidence": _label(ratio),
        "ratio": ratio,
    }


def snap_item(item: dict, form_options: dict) -> dict:
    """Snap one parsed item's labels to form options. Category drives type, which drives description."""
    cats = form_options.get("categories", []) or []
    types_map = form_options.get("types", {}) or {}
    desc_map = form_options.get("descriptions", {}) or {}
    vendors = form_options.get("vendors", []) or []

    cat_v, cat_r = _best(item.get("category"), cats)
    cat_final = cat_v or item.get("category")

    types = types_map.get(cat_final, []) if cat_final else []
    type_v, type_r = _best(item.get("type"), types)
    type_final = type_v or item.get("type")

    descs = desc_map.get(f"{cat_final}|{type_final}", []) if (cat_final and type_final) else []
    desc_v, desc_r = _best(item.get("description"), descs)

    ven_v, ven_r = _best(item.get("vendor"), vendors)

    return {
        "category": _field(item.get("category"), cat_v, cat_r),
        "type": _field(item.get("type"), type_v, type_r),
        "description": _field(item.get("description"), desc_v, desc_r),
        "vendor": _field(item.get("vendor"), ven_v, ven_r),
    }


def build_matches(items: list[dict], form_options: dict | None):
    """Return per-item snap results, or None if options haven't been discovered yet."""
    if not form_options:
        return None
    return [snap_item(it, form_options) for it in items]

"""
Receipt history: which items on a receipt were already submitted, and for whom.

One receipt is often reimbursed separately for each child. The first time a
receipt is logged, its items are saved exactly as confirmed (order, categories,
costs); each log adds which of those items went to which child. Uploading the
same file again reuses that saved reading -- no second Claude read, same items
in the same order -- so already-submitted items can start unchecked.

Receipts are identified by a fingerprint of the file's contents, so renaming a
file doesn't matter and a different receipt with the same name never matches.
Saved in receipt_history.json, which is git-ignored: it holds purchase details
and the repo is public.

    {"receipts": {"<sha256>": {"reference", "items", "reconciliation",
                               "submissions": [{"student", "sufs_id", "logged", "items": [0, 2]}]}}}
"""

import hashlib
import json
from datetime import date
from pathlib import Path

HISTORY_FILE = Path(__file__).resolve().parent.parent / "receipt_history.json"


def fingerprint(data: bytes) -> str:
    """Identifies a receipt file by its contents."""
    return hashlib.sha256(data).hexdigest()


def _load(path: Path) -> dict:
    if not path.exists():
        return {"receipts": {}}
    return json.loads(path.read_text())


def saved_reading(sha: str, path: Path = HISTORY_FILE) -> dict | None:
    """The saved entry for a receipt, or None if it has never been logged."""
    return _load(path)["receipts"].get(sha)


def record_submission(sha: str, reference: str, items: list[dict], reconciliation: dict | None,
                      student: str, sufs_id: str, path: Path = HISTORY_FILE,
                      today: date | None = None) -> dict:
    """Record that the checked items in `items` were submitted for `student`.

    `items` is the full confirmed list from the confirm page, each with an
    `include` flag. The first log of a receipt saves the items themselves; later
    logs only add a submission, so item positions stay stable.
    """
    history = _load(path)
    entry = history["receipts"].get(sha)
    if entry is None:
        entry = {
            "reference": reference,
            "items": [{k: v for k, v in item.items() if k != "include"} for item in items],
            "reconciliation": reconciliation or {},
            "submissions": [],
        }
        history["receipts"][sha] = entry
    entry["submissions"].append({
        "student": student,
        "sufs_id": sufs_id,
        "logged": f"{today or date.today():%m/%d/%Y}",
        "items": [i for i, item in enumerate(items) if item.get("include")],
    })
    path.write_text(json.dumps(history, indent=2) + "\n")
    return entry


def item_labels(entry: dict | None) -> dict[int, str]:
    """{item position: "Submitted for Sam · 12345678, Alex · 23456789"} for items already submitted."""
    if not entry:
        return {}
    who: dict[int, list[str]] = {}
    for sub in entry["submissions"]:
        for i in sub["items"]:
            who.setdefault(i, []).append(f"{sub['student']} · {sub['sufs_id']}")
    return {i: "Submitted for " + ", ".join(names) for i, names in sorted(who.items())}

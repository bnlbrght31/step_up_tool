"""
The SUFS email scan cache: what each status email said, so it's read only once.

SUFS emails never change once they arrive, but every status scan used to
download and re-read all of them -- hundreds since the first tracked year, and
more every year -- which made scans slow and ran into Gmail's per-minute limit.
Scans now reuse the saved result for any email already read and download only
new ones.

Saved in email_scan_cache.json, which is git-ignored: it holds reimbursement IDs
and amounts, and the repo is public. The cache is stamped with the version of
the email-reading code; when that changes, the old results are discarded and
everything is read fresh. Deleting the file is always safe.

    {"version": "...", "kinds": {"approved": {"<gmail message id>": {...result...}}}}
"""

import json
import os
import tempfile
from pathlib import Path

CACHE_FILE = Path(__file__).resolve().parent.parent / "email_scan_cache.json"


class ScanCache:
    """Results already read from emails, by scan kind and Gmail message ID."""

    def __init__(self, path: Path, version: str):
        self.path = path
        self.version = version
        self.kinds: dict[str, dict] = {}
        try:
            data = json.loads(path.read_text())
            if data.get("version") == version:
                self.kinds = data.get("kinds", {})
        except (FileNotFoundError, ValueError, AttributeError):
            pass    # nothing saved yet, or a damaged file: start over

    def get(self, kind: str, message_id: str) -> dict | None:
        return self.kinds.get(kind, {}).get(message_id)

    def put(self, kind: str, message_id: str, result: dict) -> None:
        self.kinds.setdefault(kind, {})[message_id] = result

    def save(self) -> None:
        """Write atomically, so an interrupted save can't leave a half-written file."""
        data = json.dumps({"version": self.version, "kinds": self.kinds}, indent=1)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".email_scan_cache.")
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp, self.path)

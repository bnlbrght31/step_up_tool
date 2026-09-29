"""
Tests for the SUFS email scan cache: each email is downloaded and read once,
and later scans reuse what it said, fetching only emails that are new.

Offline: Gmail is an in-memory fake that counts every download, and the cache
lives in a temporary file.

Run: python test_email_cache.py   (or: pytest test_email_cache.py)
"""

import base64
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fpdf import FPDF

from src import email_cache
from src import sufs_email_scanner as scanner

ROOT = Path(__file__).parent


# ---------------------------------------------------------------------------
# A fake Gmail that counts downloads
# ---------------------------------------------------------------------------

class _Result:
    def __init__(self, value):
        self.value = value

    def execute(self, num_retries=0):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _Attachments:
    def __init__(self, gmail):
        self.gmail = gmail

    def get(self, userId=None, messageId=None, id=None):
        self.gmail.attachment_downloads += 1
        return _Result({"data": base64.urlsafe_b64encode(self.gmail.attachments[id]).decode()})


class _Messages:
    def __init__(self, gmail):
        self.gmail = gmail

    def list(self, userId=None, q="", maxResults=None, pageToken=None):
        ids = [mid for mid, (subject, _msg) in self.gmail.inbox.items() if subject in q]
        return _Result({"messages": [{"id": i} for i in ids]})

    def get(self, userId=None, id=None, format=None):
        self.gmail.downloads += 1
        if id in self.gmail.fail_once:
            self.gmail.fail_once.discard(id)
            return _Result(RuntimeError(f"download of {id} failed"))
        return _Result(self.gmail.inbox[id][1])

    def attachments(self):
        return _Attachments(self.gmail)


class FakeGmail:
    def __init__(self):
        self.inbox = {}             # id -> (subject fragment, message)
        self.attachments = {}       # attachment id -> bytes
        self.downloads = 0
        self.attachment_downloads = 0
        self.fail_once = set()

    def users(self):
        return self

    def messages(self):
        return _Messages(self)

    def add(self, mid, subject, body, pdf=None):
        text = {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}}
        parts = [text]
        if pdf is not None:
            self.attachments[f"att-{mid}"] = pdf
            parts.append({"filename": "remittance.pdf", "body": {"attachmentId": f"att-{mid}"}})
        self.inbox[mid] = (subject, {"id": mid, "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Date", "value": "Thu, 20 Aug 2026 10:00:00 -0400"}],
            "parts": parts,
        }})


APPROVED = "Reimbursement request approved"
REMITTANCE = "Remittance Advice"


def _approval(n):
    return (f"Reimbursement ID: 1000000{n}\nStudent’s Name: Sam\n"
            f"your reimbursement request for Books in the amount of $1{n}.00 was approved")


def _remittance_pdf(line_item):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, f"Invoice {line_item}")
    return bytes(pdf.output())


def _setup(*approvals):
    """A fake inbox with numbered approval emails, and a fresh temporary cache."""
    gmail = FakeGmail()
    for n in approvals:
        gmail.add(f"a{n}", APPROVED, _approval(n))
    scanner._get_gmail_service = lambda: gmail
    cache = Path(tempfile.mkdtemp()) / "email_scan_cache.json"
    scanner.cache_file = lambda: cache
    return gmail, cache


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_a_second_scan_downloads_nothing_it_has_already_read():
    gmail, _ = _setup(1, 2, 3)
    first = scanner.scan_approved_emails("2025/07/01")
    assert gmail.downloads == 3
    second = scanner.scan_approved_emails("2025/07/01")
    assert gmail.downloads == 3, "the second scan re-downloaded emails it had already read"
    assert second == first


def test_a_new_email_is_the_only_one_downloaded():
    gmail, _ = _setup(1, 2, 3)
    scanner.scan_approved_emails("2025/07/01")
    gmail.add("a4", APPROVED, _approval(4))
    results = scanner.scan_approved_emails("2025/07/01")
    assert gmail.downloads == 4
    assert [r["reimbursement_id"] for r in results] == ["10000001", "10000002", "10000003", "10000004"]


def test_remittance_pdfs_are_not_downloaded_again():
    gmail, _ = _setup()
    gmail.add("r1", REMITTANCE, "Payment of $25.00 attached", pdf=_remittance_pdf("10000001-1"))
    first = scanner.scan_remittance_emails("2025/07/01")
    assert first[0]["line_items"] == ["10000001-1"]
    assert (gmail.downloads, gmail.attachment_downloads) == (1, 1)
    scanner.scan_remittance_emails("2025/07/01")
    assert (gmail.downloads, gmail.attachment_downloads) == (1, 1)


def test_cached_results_match_a_fresh_read():
    gmail, _ = _setup(1, 2)
    scanner.scan_approved_emails("2025/07/01")
    cached = scanner.scan_approved_emails("2025/07/01")
    fresh_cache = Path(tempfile.mkdtemp()) / "email_scan_cache.json"
    scanner.cache_file = lambda: fresh_cache
    assert scanner.scan_approved_emails("2025/07/01") == cached


def test_changing_the_email_reading_code_rereads_everything():
    gmail, _ = _setup(1, 2, 3)
    scanner.scan_approved_emails("2025/07/01")
    real = scanner.READER_VERSION
    scanner.READER_VERSION = "reading code changed"
    try:
        scanner.scan_approved_emails("2025/07/01")
    finally:
        scanner.READER_VERSION = real
    assert gmail.downloads == 6


def test_a_failed_read_is_not_cached_and_earlier_progress_is_kept():
    gmail, _ = _setup(1, 2, 3)
    gmail.fail_once.add("a3")
    try:
        scanner.scan_approved_emails("2025/07/01")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the failed download to surface")
    assert gmail.downloads == 3
    results = scanner.scan_approved_emails("2025/07/01")      # resumes: only a3 again
    assert gmail.downloads == 4 and len(results) == 3


def test_a_damaged_cache_file_is_rebuilt():
    gmail, cache = _setup(1, 2)
    cache.write_text("{ not json")
    assert len(scanner.scan_approved_emails("2025/07/01")) == 2
    scanner.scan_approved_emails("2025/07/01")
    assert gmail.downloads == 2


def test_the_cache_file_is_kept_out_of_git():
    """It holds reimbursement IDs and amounts, and the repo is public."""
    rel = email_cache.CACHE_FILE.relative_to(ROOT)
    assert subprocess.run(["git", "check-ignore", "-q", str(rel)], cwd=ROOT).returncode == 0, \
        f"{rel} is not git-ignored"


def test_scanner_tests_never_touch_the_real_cache():
    _setup(1)
    assert scanner.cache_file() != email_cache.CACHE_FILE


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} tests passed; each SUFS email is downloaded and read once.")

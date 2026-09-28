"""
Tests that the tracking sheet stays complete and free of duplicates.

Covers three ways data went missing or got doubled:
  - logging the same SUFS submission twice appended duplicate line items;
  - reads of a Line Items tab stopped at row 500;
  - the Amazon scan read only the first 500 matching emails.

Runs against fake Sheets and Gmail services, so it never touches live data.

Run: python test_sheets_integrity.py   (or: pytest test_sheets_integrity.py)
"""

import base64
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fake_sheets import FakeSheets
from src import sheets_logger

CURRENT, PRIOR = sheets_logger.LINE_ITEMS_TAB, sheets_logger.LINE_ITEMS_TABS[0]
ITEM = {"cost": "20.00", "tax": "1.40", "description": "Workbook",
        "vendor": "Target", "purchase_date": "08/14/2026"}


def _fake(current_rows=(), prior_rows=()):
    header = sheets_logger.TESTING_HEADER
    tabs = {"Unsubmitted": [sheets_logger.UNSUBMITTED_HEADER],
            PRIOR: [header, *map(list, prior_rows)]}
    if CURRENT != PRIOR:
        tabs[CURRENT] = [header, *map(list, current_rows)]
    svc = FakeSheets(tabs)
    sheets_logger._get_service = lambda: svc
    return svc


def _logged_row(sufs_line_id):
    return ["Sam", "Workbook", "Target", "x.pdf", "21.40", "08/14/2026",
            "submitted", sufs_line_id, "08/20/2026"]


# ---------------------------------------------------------------------------
# Logging a submission twice
# ---------------------------------------------------------------------------

def test_logging_a_new_submission_appends_its_line_items():
    svc = _fake()
    sheets_logger.log_submission_to_testing("Sam", "10000001", [ITEM, ITEM], "x.pdf")
    ids = [r[7] for r in svc.tabs[CURRENT][1:]]
    assert ids == ["10000001-1", "10000001-2"]


def test_logging_the_same_submission_again_is_refused():
    svc = _fake()
    sheets_logger.log_submission_to_testing("Sam", "10000001", [ITEM], "x.pdf")
    try:
        sheets_logger.log_submission_to_testing("Sam", "10000001", [ITEM], "x.pdf")
    except sheets_logger.AlreadyLoggedError as e:
        assert "10000001" in str(e)
    else:
        raise AssertionError("expected AlreadyLoggedError on the second log")
    assert len(svc.appends) == 1, "the refused log must not append anything"


def test_a_submission_logged_in_a_prior_year_is_still_refused():
    """SUFS IDs are unique across years, so every Line Items tab is checked."""
    svc = _fake(prior_rows=[_logged_row("10000001-1")])
    try:
        sheets_logger.log_submission_to_testing("Sam", "10000001", [ITEM], "x.pdf")
    except sheets_logger.AlreadyLoggedError:
        pass
    else:
        raise AssertionError("expected AlreadyLoggedError")
    assert svc.appends == []


def test_an_id_that_merely_starts_with_the_same_digits_is_not_a_duplicate():
    """'1000000' must not collide with an existing '10000001-1'."""
    svc = _fake(current_rows=[_logged_row("10000001-1")])
    sheets_logger.log_submission_to_testing("Sam", "1000000", [ITEM], "x.pdf")
    assert svc.tabs[CURRENT][-1][7] == "1000000-1"


def test_the_route_reports_a_duplicate_log_as_a_conflict():
    import tempfile
    from flask import Flask
    from src import submission_routes
    from src.submission_routes import bp

    temp_folder = Path(tempfile.mkdtemp())       # never the real receipts folder
    submission_routes.receipts_folder = lambda: temp_folder
    svc = _fake(current_rows=[_logged_row("10000001-1")])
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(bp)
    r = app.test_client().post("/log-submission", json={
        "student": "Sam", "sufs_id": "10000001",
        "items": [dict(ITEM, include=True)],
    })
    assert r.status_code == 409
    assert "already logged" in r.get_json()["error"]
    assert svc.appends == []


# ---------------------------------------------------------------------------
# Reading every row of a Line Items tab
# ---------------------------------------------------------------------------

def test_line_item_reads_are_not_capped_at_500_rows():
    """Last year's tab reached 403 rows; a busier year must not lose any."""
    rows = [_logged_row(f"20000000-{i}") for i in range(1, 601)]
    _fake(prior_rows=rows)
    ids = {r["sufs_reimb_id"] for r in sheets_logger.read_testing_rows()}
    assert "20000000-600" in ids
    assert len(ids) == 600


# ---------------------------------------------------------------------------
# Reading every matching Gmail message
# ---------------------------------------------------------------------------

class FakeGmail:
    """Serves Gmail list results in pages of `page_size`, like the real API."""

    def __init__(self, emails: dict, page_size: int):
        self._emails = emails             # id -> full message dict
        self.page_size = page_size
        self.list_calls = 0

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, userId=None, q=None, maxResults=None, pageToken=None):
        self.list_calls += 1
        ids = sorted(self._emails)
        start = int(pageToken or 0)
        resp = {"messages": [{"id": i} for i in ids[start:start + self.page_size]]}
        if start + self.page_size < len(ids):
            resp["nextPageToken"] = str(start + self.page_size)
        return _Result(resp)

    def get(self, userId=None, id=None, format=None):
        return _Result(self._emails[id])


class _Result:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


@contextmanager
def _patched(module, **attrs):
    """Temporarily replace module attributes, restoring them afterwards."""
    saved = {k: getattr(module, k) for k in attrs}
    for k, v in attrs.items():
        setattr(module, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(module, k, v)


def _email(n: int, subject: str) -> dict:
    order = f"111-{n:07d}-{n:07d}"
    body = base64.urlsafe_b64encode(f"Order #{order}\nGrand Total: $10.00".encode()).decode()
    return {"payload": {
        "mimeType": "text/plain",
        "headers": [{"name": "Subject", "value": subject},
                    {"name": "Date", "value": "Fri, 14 Aug 2026 10:00:00 -0400"}],
        "body": {"data": body},
    }}


# The fake's pages are small on purpose: the behaviour under test is following
# nextPageToken, and 500-per-page fixtures would only make the tests slow.

def test_amazon_scan_reads_past_the_first_page_of_results():
    from src import amazon_scanner

    gmail = FakeGmail({f"m{n}": _email(n, f'Ordered: "Workbook {n}"') for n in range(1, 8)},
                      page_size=3)
    with _patched(amazon_scanner,
                  _get_gmail_service=lambda: gmail,
                  batch_check_eligibility=lambda descs: ([None] * len(descs), 0.0),
                  scan_return_emails=lambda after_date: {}):
        orders, _after, _cost = amazon_scanner.scan_amazon_orders(set(), from_date="2026-07-01")
    assert len(orders) == 7, f"expected all 7 orders across 3 pages, got {len(orders)}"


def test_return_scan_reads_past_the_first_page_of_results():
    from src import amazon_scanner

    gmail = FakeGmail({f"r{n}": _email(n, f"Your refund for Workbook {n}.") for n in range(1, 6)},
                      page_size=2)
    with _patched(amazon_scanner, _get_gmail_service=lambda: gmail):
        found = amazon_scanner.scan_return_emails("2026/07/01")
    assert len(found) == 5, f"expected all 5 refunded orders, got {len(found)}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} tests passed; no duplicate logs, no rows or emails dropped.")

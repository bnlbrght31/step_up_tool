"""
Tests for receipt history: remembering which items on a receipt were already
submitted, and for which child, so the next child's upload of the same file
reuses the saved reading and starts those items unchecked.

Runs against temporary history files and FakeSheets; never touches real data.

Run: python test_receipt_history.py   (or: pytest test_receipt_history.py)
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask

from fake_sheets import FakeSheets
from src import note_routes, receipt_history, sheets_logger, students, submission_routes

ROOT = Path(__file__).parent


def _tmp_history() -> Path:
    return Path(tempfile.mkdtemp()) / "receipt_history.json"


def _items(*included):
    """Confirmed items as the confirm page sends them, with include flags."""
    names = ["Crayons", "Rulers", "Notebook", "Glue"]
    return [{"include": inc, "description": names[i], "category": "Instructional Materials",
             "cost": 1.0 + i, "tax": 0.07, "quantity": 1, "vendor": "Walmart",
             "purchase_date": "07/23/2026"} for i, inc in enumerate(included)]


RECON = {"grand_total": 87.36, "computed_total": 87.36, "has_totals": True}


# ---------------------------------------------------------------------------
# The history file
# ---------------------------------------------------------------------------

def test_a_fingerprint_depends_on_the_files_contents_not_its_name():
    assert receipt_history.fingerprint(b"receipt A") == receipt_history.fingerprint(b"receipt A")
    assert receipt_history.fingerprint(b"receipt A") != receipt_history.fingerprint(b"receipt B")


def test_a_logged_receipt_is_remembered_with_its_items_and_who_they_went_to():
    path = _tmp_history()
    receipt_history.record_submission("abc", "IMG_1", _items(True, True, False), RECON,
                                      "Sam", "10000001", path)
    saved = receipt_history.saved_reading("abc", path)
    assert saved["reference"] == "IMG_1"
    assert [i["description"] for i in saved["items"]] == ["Crayons", "Rulers", "Notebook"]
    assert all("include" not in i for i in saved["items"])
    assert saved["reconciliation"] == RECON
    assert [(s["student"], s["sufs_id"], s["items"]) for s in saved["submissions"]] == [
        ("Sam", "10000001", [0, 1])]


def test_a_later_log_adds_a_child_but_keeps_the_first_reading():
    path = _tmp_history()
    receipt_history.record_submission("abc", "IMG_1", _items(True, True, False), RECON,
                                      "Sam", "10000001", path)
    edited = _items(False, False, True)
    edited[2]["description"] = "Changed on the second page"
    receipt_history.record_submission("abc", "IMG_1", edited, RECON, "Alex", "10000002", path)
    saved = receipt_history.saved_reading("abc", path)
    assert saved["items"][2]["description"] == "Notebook"
    assert [(s["student"], s["items"]) for s in saved["submissions"]] == [("Sam", [0, 1]), ("Alex", [2])]


def test_a_receipt_never_logged_has_no_saved_reading():
    assert receipt_history.saved_reading("nope", _tmp_history()) is None


def test_items_are_labelled_with_every_child_they_were_submitted_for():
    path = _tmp_history()
    receipt_history.record_submission("abc", "IMG_1", _items(True, True, False), RECON,
                                      "Sam", "10000001", path)
    receipt_history.record_submission("abc", "IMG_1", _items(False, True, False), RECON,
                                      "Alex", "10000002", path)
    labels = receipt_history.item_labels(receipt_history.saved_reading("abc", path))
    assert labels == {0: "Submitted for Sam · 10000001",
                      1: "Submitted for Sam · 10000001, Alex · 10000002"}


def test_the_history_file_is_kept_out_of_git():
    """It holds purchase details, and the repo is public."""
    rel = receipt_history.HISTORY_FILE.relative_to(ROOT)
    assert subprocess.run(["git", "check-ignore", "-q", str(rel)], cwd=ROOT).returncode == 0, \
        f"{rel} is not git-ignored"


# ---------------------------------------------------------------------------
# Logging records the submission
# ---------------------------------------------------------------------------

def _sheet():
    tabs = {"Unsubmitted": [sheets_logger.UNSUBMITTED_HEADER]}
    for tab in sheets_logger.LINE_ITEMS_TABS:
        tabs[tab] = [sheets_logger.TESTING_HEADER]
    svc = FakeSheets(tabs)
    sheets_logger._get_service = lambda: svc
    return svc


def _log_client(history, session_data):
    tmp = Path(tempfile.mkdtemp())
    submission_routes.receipts_folder = lambda: tmp
    submission_routes.students_file = lambda: tmp / "students.json"
    submission_routes.history_file = lambda: history
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(submission_routes.bp)
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(session_data)
    return client


UPLOADED = {"invoice_filename": "IMG_1.pdf", "invoice_sha256": "abc", "reconciliation": RECON}


def test_logging_records_exactly_the_checked_items_for_that_child():
    _sheet()
    history = _tmp_history()
    client = _log_client(history, UPLOADED)
    r = client.post("/log-submission", json={"student": "Sam", "sufs_id": "10000001",
                                             "items": _items(True, False, True)})
    assert r.get_json()["success"]
    saved = receipt_history.saved_reading("abc", history)
    assert saved["reference"] == "IMG_1" and saved["submissions"][0]["items"] == [0, 2]


def test_the_history_uses_the_saved_spelling_of_the_childs_name():
    _sheet()
    history = _tmp_history()
    client = _log_client(history, UPLOADED)
    settings = history.parent / "students.json"
    students.save_students([{"name": "Sam", "student_id": ""}], settings)
    submission_routes.students_file = lambda: settings
    client.post("/log-submission", json={"student": "sAM", "sufs_id": "10000001",
                                         "items": _items(True)})
    assert receipt_history.saved_reading("abc", history)["submissions"][0]["student"] == "Sam"


def test_without_an_uploaded_file_nothing_is_recorded():
    _sheet()
    history = _tmp_history()
    client = _log_client(history, {"invoice_filename": "IMG_1.pdf"})
    assert client.post("/log-submission", json={"student": "Sam", "sufs_id": "10000001",
                                                "items": _items(True)}).get_json()["success"]
    assert not history.exists()


def test_a_history_failure_never_fails_the_log():
    _sheet()
    client = _log_client(_tmp_history(), UPLOADED)
    real = receipt_history.record_submission

    def _broken(*_a, **_k):
        raise OSError("disk full")
    receipt_history.record_submission = _broken
    try:
        data = client.post("/log-submission", json={"student": "Sam", "sufs_id": "10000001",
                                                    "items": _items(True)}).get_json()
    finally:
        receipt_history.record_submission = real
    assert data["success"]


def test_route_tests_never_touch_the_real_history_file():
    _log_client(_tmp_history(), UPLOADED)
    assert submission_routes.history_file() != receipt_history.HISTORY_FILE


# ---------------------------------------------------------------------------
# The confirm page's lookup
# ---------------------------------------------------------------------------

def _note_client(history, session_data):
    note_routes.history_file = lambda: history
    app = Flask(__name__, template_folder=str(ROOT / "templates"))
    app.secret_key = "test"
    app.register_blueprint(note_routes.bp)
    client = app.test_client()
    with client.session_transaction() as s:
        s.update(session_data)
    return client


def test_the_lookup_labels_items_already_submitted():
    history = _tmp_history()
    receipt_history.record_submission("abc", "IMG_1", _items(True, False, False), RECON,
                                      "Sam", "10000001", history)
    data = _note_client(history, dict(UPLOADED, reused_reading=True)).get(
        "/receipt-history/status").get_json()
    assert data == {"reused": True, "labels": {"0": "Submitted for Sam · 10000001"}}


def test_a_receipt_with_no_history_has_no_labels():
    data = _note_client(_tmp_history(), UPLOADED).get("/receipt-history/status").get_json()
    assert data == {"reused": False, "labels": {}}


def test_the_confirm_page_unchecks_and_labels_submitted_items():
    page = (ROOT / "templates" / "confirm.html").read_text()
    assert "fetch('/receipt-history/status')" in page
    assert 'id="reused-banner"' in page
    assert "toggleCard(i)" in page           # unchecking updates the card and the totals


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} tests passed; the next child's upload starts with the right items.")

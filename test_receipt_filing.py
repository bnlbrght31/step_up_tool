"""
Tests for filing a receipt into the year folder's Submitted/ subfolder once it's
done: right after logging when nothing says more children are coming, or when
"Remove from Unsubmitted" is chosen. "Keep, more kids to submit" leaves it for
the next child's upload.

Runs against temporary folders and FakeSheets; never touches the real folder.

Run: python test_receipt_filing.py   (or: pytest test_receipt_filing.py)
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flask import Flask
from werkzeug.utils import secure_filename

from fake_sheets import FakeSheets
from src import receipt_folder as rf
from src import sheets_logger, students, submission_routes

ITEM = {"include": True, "cost": "20.00", "tax": "1.40", "description": "Workbook",
        "vendor": "Target", "purchase_date": "08/14/2026"}


def _sheet(staged=(), fake=FakeSheets):
    tabs = {"Unsubmitted": [sheets_logger.UNSUBMITTED_HEADER]
            + [["", "item", "Store", ref, "1.00", "08/01/2026", ""] for ref in staged]}
    for tab in sheets_logger.LINE_ITEMS_TABS:
        tabs[tab] = [sheets_logger.TESTING_HEADER]
    svc = fake(tabs)
    sheets_logger._get_service = lambda: svc
    return svc


def _folder(*names) -> Path:
    """A temporary year folder holding `names` (subfolder paths allowed)."""
    root = Path(tempfile.mkdtemp())
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(b"%PDF-1.4 placeholder")
    return root


def _client(folder, invoice):
    """A client for the submission routes, with `invoice` as the uploaded receipt.

    Both the receipts folder and the Students settings file are temporary, so
    no test reaches the real receipts or reads the real student list.
    """
    submission_routes.receipts_folder = lambda: folder
    no_students = Path(tempfile.mkdtemp()) / "students.json"
    submission_routes.students_file = lambda: no_students
    submission_routes.history_file = lambda: no_students.with_name("receipt_history.json")
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(submission_routes.bp)
    client = app.test_client()
    with client.session_transaction() as s:
        s["invoice_filename"] = invoice
    return client


def _log(client):
    return client.post("/log-submission", json={
        "student": "Sam", "sufs_id": "10000001", "items": [ITEM]}).get_json()


def _top_level(folder):
    return sorted(p.name for p in folder.iterdir() if p.is_file())


def _submitted(folder):
    sub = folder / rf.SUBMITTED
    return sorted(p.name for p in sub.iterdir()) if sub.is_dir() else []


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def test_a_receipt_not_in_unsubmitted_is_filed_as_soon_as_it_is_logged():
    _sheet()
    folder = _folder("Target 8-14-26.pdf")
    data = _log(_client(folder, "Target_8-14-26.pdf"))
    assert data["success"]
    assert data["filed"]["moved"] == ["Target 8-14-26.pdf"]
    assert _submitted(folder) == ["Target 8-14-26.pdf"] and _top_level(folder) == []


def test_a_staged_receipt_waits_for_the_remove_or_keep_choice():
    _sheet(staged=["IMG_1"])
    folder = _folder("IMG_1.pdf")
    data = _log(_client(folder, "IMG_1.pdf"))
    assert data["filed"]["deferred"] is True and data["filed"]["moved"] == []
    assert _top_level(folder) == ["IMG_1.pdf"]


def test_every_top_level_file_of_the_receipt_moves_but_originals_stay():
    _sheet()
    folder = _folder("IMG_2.pdf", "IMG_2.jpeg", "Originals/IMG_2.HEIC")
    _log(_client(folder, "IMG_2.pdf"))
    assert _submitted(folder) == ["IMG_2.jpeg", "IMG_2.pdf"]
    assert (folder / "Originals" / "IMG_2.HEIC").exists()


def test_a_receipt_the_upload_page_renamed_still_finds_its_file():
    _sheet()
    folder = _folder("Lowe's 8-1-26.pdf")
    data = _log(_client(folder, secure_filename("Lowe's 8-1-26.pdf")))
    assert data["filed"]["moved"] == ["Lowe's 8-1-26.pdf"]


def test_a_receipt_missing_from_the_folder_is_reported_not_an_error():
    _sheet()
    folder = _folder("other.pdf")
    data = _log(_client(folder, "IMG_3.pdf"))
    assert data["success"] and data["filed"]["moved"] == [] and not data["filed"].get("error")
    assert _top_level(folder) == ["other.pdf"]


def test_a_missing_year_folder_never_breaks_the_log():
    _sheet()
    data = _log(_client(Path(tempfile.mkdtemp()) / "2027-2028", "IMG_4.pdf"))
    assert data["success"] and data["filed"]["moved"] == []


def test_a_failed_move_is_reported_without_failing_the_log():
    _sheet()
    folder = _folder("IMG_5.pdf")
    real = rf.file_as_submitted

    def _broken(*_):
        raise PermissionError("Operation not permitted")
    rf.file_as_submitted = _broken
    try:
        data = _log(_client(folder, "IMG_5.pdf"))
    finally:
        rf.file_as_submitted = real
    assert data["success"] and "not permitted" in data["filed"]["error"]
    assert _top_level(folder) == ["IMG_5.pdf"]


def test_an_unreadable_unsubmitted_tab_leaves_the_file_in_place():
    """If the app can't tell whether more kids are coming, it doesn't guess."""
    class _NoUnsubmittedRead(FakeSheets):
        def get(self, spreadsheetId=None, range=None, **kw):
            if range and range.startswith("Unsubmitted!"):
                raise RuntimeError("503")
            return super().get(spreadsheetId=spreadsheetId, range=range, **kw)
    _sheet(fake=_NoUnsubmittedRead)
    folder = _folder("IMG_6.pdf")
    data = _log(_client(folder, "IMG_6.pdf"))
    assert data["success"] and data["filed"]["moved"] == [] and data["filed"]["deferred"]
    assert _top_level(folder) == ["IMG_6.pdf"]


# ---------------------------------------------------------------------------
# The Remove / Keep choice
# ---------------------------------------------------------------------------

def test_remove_from_unsubmitted_files_the_receipt():
    _sheet(staged=["IMG_7"])
    folder = _folder("IMG_7.pdf")
    client = _client(folder, "IMG_7.pdf")
    _log(client)
    data = client.post("/unsubmitted/remove", json={"order_number": "IMG_7"}).get_json()
    assert data["removed"] is True and data["filed"]["moved"] == ["IMG_7.pdf"]
    assert _submitted(folder) == ["IMG_7.pdf"]


def test_keep_leaves_the_receipt_for_the_next_childs_upload():
    _sheet(staged=["IMG_8"])
    folder = _folder("IMG_8.pdf")
    client = _client(folder, "IMG_8.pdf")
    _log(client)
    client.post("/unsubmitted/mark", json={"order_number": "IMG_8", "student": "Sam",
                                           "sufs_id": "10000001"})
    assert _top_level(folder) == ["IMG_8.pdf"] and _submitted(folder) == []


# ---------------------------------------------------------------------------
# Student spelling
# ---------------------------------------------------------------------------

def _saved_students(*names):
    """Save `names` as the children in a temporary Students file the routes will read."""
    path = Path(tempfile.mkdtemp()) / "students.json"
    students.save_students([{"name": n, "student_id": ""} for n in names], path)
    submission_routes.students_file = lambda: path


def test_logging_uses_the_saved_spelling_of_a_childs_name():
    svc = _sheet()
    client = _client(_folder(), "IMG_9.pdf")
    _saved_students("Sam")
    client.post("/log-submission", json={"student": "sAm", "sufs_id": "10000001", "items": [ITEM]})
    assert svc.tabs[sheets_logger.LINE_ITEMS_TAB][-1][0] == "Sam"


def test_logging_keeps_a_name_that_isnt_saved_as_typed():
    svc = _sheet()
    client = _client(_folder(), "IMG_9.pdf")
    _saved_students("Sam")
    client.post("/log-submission", json={"student": "Casey", "sufs_id": "10000001", "items": [ITEM]})
    assert svc.tabs[sheets_logger.LINE_ITEMS_TAB][-1][0] == "Casey"


def test_the_keep_stamp_uses_the_saved_spelling():
    _sheet(staged=["IMG_10"])
    client = _client(_folder("IMG_10.pdf"), "IMG_10.pdf")
    _saved_students("Sam")
    data = client.post("/unsubmitted/mark", json={"order_number": "IMG_10", "student": "SAM",
                                                  "sufs_id": "10000001"}).get_json()
    assert data["status"].startswith("partial: Sam 10000001")


def test_route_tests_never_read_the_real_students_file():
    _client(_folder(), "IMG_9.pdf")
    assert submission_routes.students_file() != students.STUDENTS_FILE


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def test_the_confirm_page_says_where_the_receipt_file_went():
    page = (Path(__file__).parent / "templates" / "confirm.html").read_text()
    assert page.count("showFiled(data.filed") == 2      # after logging, and after Remove
    assert 'id="filed-note"' in page
    assert "stays in the folder for the next child" in page   # after Keep


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} tests passed; finished receipts are filed in Submitted/.")

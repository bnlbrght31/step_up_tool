"""
Tests for the shared-receipt note: when a receipt was already submitted for one
child, a PDF for the next child's submission names the earlier submissions
(child, SUFS student ID, reimbursement ID, items).

Runs offline: temporary settings files, FakeSheets and no Claude calls.

Run: python test_receipt_note.py   (or: pytest test_receipt_note.py)
"""

import io
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pdfplumber
from werkzeug.utils import secure_filename

from fake_sheets import FakeSheets
from src import receipt_note, sheets_logger, students

ROOT = Path(__file__).parent


def _tmp_settings():
    return Path(tempfile.mkdtemp()) / "students.json"


# ---------------------------------------------------------------------------
# Student IDs
# ---------------------------------------------------------------------------

def test_students_round_trip_through_the_settings_file():
    path = _tmp_settings()
    students.save_students([{"name": "Sam", "student_id": "1234567"},
                            {"name": "Alex", "student_id": ""}], path)
    assert students.load_students(path) == [{"name": "Sam", "student_id": "1234567"},
                                            {"name": "Alex", "student_id": ""}]


def test_no_settings_file_means_no_students():
    assert students.load_students(_tmp_settings()) == []


def test_blank_rows_are_dropped_and_values_trimmed():
    path = _tmp_settings()
    students.save_students([{"name": "  Sam ", "student_id": " 1234567 "},
                            {"name": "", "student_id": ""}], path)
    assert students.load_students(path) == [{"name": "Sam", "student_id": "1234567"}]


def test_the_same_child_twice_is_refused():
    try:
        students.save_students([{"name": "Sam", "student_id": "1"},
                                {"name": "sam", "student_id": "2"}], _tmp_settings())
    except ValueError as e:
        assert "Sam" in str(e) or "sam" in str(e)
    else:
        raise AssertionError("expected ValueError for a duplicate name")


def test_student_id_lookup_ignores_capitalisation_and_spacing():
    path = _tmp_settings()
    students.save_students([{"name": "Sam", "student_id": "1234567"}], path)
    listed = students.load_students(path)
    assert students.student_id_for("SAm", listed) == "1234567"
    assert students.student_id_for(" sam ", listed) == "1234567"
    assert students.student_id_for("Alex", listed) == ""


def test_the_settings_file_is_kept_out_of_git():
    """The repo is public; student IDs must never be committed."""
    rel = students.STUDENTS_FILE.relative_to(ROOT)
    ignored = subprocess.run(["git", "check-ignore", "-q", str(rel)], cwd=ROOT).returncode == 0
    assert ignored, f"{rel} is not git-ignored"


# ---------------------------------------------------------------------------
# Finding earlier submissions of a receipt
# ---------------------------------------------------------------------------

PRIOR_TAB, CURRENT_TAB = sheets_logger.LINE_ITEMS_TABS[0], sheets_logger.LINE_ITEMS_TABS[-1]


def _line(student, item, invoice, price, reimb_line_id, submitted="08/20/2026"):
    return [student, item, "Walmart", invoice, price, "07/23/2026", "submitted",
            reimb_line_id, submitted]


def _sheet(prior=(), current=()):
    tabs = {PRIOR_TAB: [sheets_logger.TESTING_HEADER, *map(list, prior)]}
    if CURRENT_TAB != PRIOR_TAB:
        tabs[CURRENT_TAB] = [sheets_logger.TESTING_HEADER, *map(list, current)]
    svc = FakeSheets(tabs)
    sheets_logger._get_service = lambda: svc
    return svc


def test_earlier_submissions_are_grouped_by_reimbursement_across_years():
    _sheet(prior=[_line("Sam", "Crayons", "IMG_1698.pdf", "0.53", "10000001-1"),
                  _line("Sam", "Rulers", "IMG_1698.pdf", "1.00", "10000001-2"),
                  _line("Sam", "Unrelated", "other.pdf", "9.99", "10000009-1")],
           current=[_line("Alex", "Notebook", "IMG_1698.pdf", "$2.10", "10000002-1", "09/02/2026")])
    subs = receipt_note.prior_submissions("IMG_1698")
    assert [(s["student"], s["reimbursement_id"]) for s in subs] == [("Sam", "10000001"), ("Alex", "10000002")]
    assert [i["description"] for i in subs[0]["items"]] == ["Crayons", "Rulers"]
    assert subs[0]["total"] == 1.53
    assert subs[1]["date_submitted"] == "09/02/2026" and subs[1]["total"] == 2.10


def test_a_receipt_the_upload_page_renamed_still_finds_its_earlier_submission():
    _sheet(prior=[_line("Sam", "Paint", secure_filename("Lowe's 8-1-26.pdf"), "5.00", "10000003-1")])
    assert [s["reimbursement_id"] for s in receipt_note.prior_submissions("Lowe's 8-1-26")] == ["10000003"]


def test_a_receipt_never_submitted_has_no_earlier_submissions():
    _sheet(prior=[_line("Sam", "Crayons", "IMG_1698.pdf", "0.53", "10000001-1")])
    assert receipt_note.prior_submissions("IMG_9999") == []
    assert receipt_note.prior_submissions("") == []


# ---------------------------------------------------------------------------
# The note PDF
# ---------------------------------------------------------------------------

def _pdf_text(data: bytes) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


SAM_SUBMISSION = {"student": "Sam", "reimbursement_id": "10000001", "date_submitted": "08/20/2026",
                  "items": [{"description": "Crayons", "price": 0.53},
                            {"description": "Rulers", "price": 1.00}],
                  "total": 1.53}
RECEIPT = {"store": "Walmart", "date": "07/23/2026", "total": 87.36}


def test_the_note_names_the_child_student_id_reimbursement_and_items():
    text = _pdf_text(receipt_note.build_note_pdf(
        "IMG_1698", [SAM_SUBMISSION], RECEIPT, [{"name": "Sam", "student_id": "1234567"}]))
    for expected in ("Walmart", "07/23/2026", "$87.36", "IMG_1698",
                     "Sam", "SUFS student ID 1234567", "Reimbursement 10000001",
                     "submitted 08/20/2026", "Crayons", "$0.53", "Rulers", "$1.00", "$1.53",
                     "remaining items"):
        assert expected in text, f"{expected!r} missing from:\n{text}"


def test_a_child_without_a_saved_student_id_is_marked_not_on_file():
    text = _pdf_text(receipt_note.build_note_pdf("IMG_1698", [SAM_SUBMISSION], RECEIPT, []))
    assert "SUFS student ID not on file" in text


def test_the_note_lists_every_earlier_submission():
    alex = dict(SAM_SUBMISSION, student="Alex", reimbursement_id="10000002")
    text = _pdf_text(receipt_note.build_note_pdf("IMG_1698", [SAM_SUBMISSION, alex], RECEIPT, []))
    assert "Reimbursement 10000001" in text and "Reimbursement 10000002" in text


def test_characters_the_pdf_font_lacks_do_not_break_the_note():
    """Item descriptions come from Claude and can hold dashes, quotes or emoji."""
    odd = dict(SAM_SUBMISSION, items=[{"description": "Crayons — 24 ct “jumbo” 🖍", "price": 0.53}])
    text = _pdf_text(receipt_note.build_note_pdf("IMG_1698", [odd], RECEIPT, []))
    assert 'Crayons - 24 ct "jumbo"' in text


def test_a_receipt_with_unknown_totals_still_produces_a_note():
    text = _pdf_text(receipt_note.build_note_pdf("IMG_1698", [SAM_SUBMISSION], {}, []))
    assert "IMG_1698" in text and "Reimbursement 10000001" in text


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _client(settings, session_data=None):
    """A test client with the note blueprint, a temporary Students file and a session."""
    from flask import Flask
    from src import note_routes

    note_routes.settings_path = lambda: settings
    app = Flask(__name__, template_folder=str(ROOT / "templates"))
    app.secret_key = "test"
    app.register_blueprint(note_routes.bp)
    client = app.test_client()
    if session_data:
        with client.session_transaction() as s:
            s.update(session_data)
    return client


UPLOADED_IMG_1698 = {
    "invoice_filename": "IMG_1698.pdf",
    "items": [{"vendor": "Walmart", "purchase_date": "07/23/2026", "description": "Glue"}],
    "reconciliation": {"grand_total": 87.36, "computed_total": 87.36},
}


def test_the_confirm_page_lookup_lists_earlier_submissions_and_missing_ids():
    _sheet(prior=[_line("Sam", "Crayons", "IMG_1698.pdf", "0.53", "10000001-1"),
                  _line("Alex", "Rulers", "IMG_1698.pdf", "1.00", "10000002-1")])
    settings = _tmp_settings()
    students.save_students([{"name": "Sam", "student_id": "1234567"}], settings)
    data = _client(settings, UPLOADED_IMG_1698).get("/note/prior").get_json()
    assert data["reference"] == "IMG_1698"
    assert [(s["student"], s["reimbursement_id"], s["item_count"], s["total"])
            for s in data["submissions"]] == [("Sam", "10000001", 1, 0.53), ("Alex", "10000002", 1, 1.0)]
    assert data["missing_ids"] == ["Alex"]


def test_no_upload_or_no_earlier_submission_means_no_panel():
    _sheet(prior=[_line("Sam", "Crayons", "IMG_1698.pdf", "0.53", "10000001-1")])
    assert _client(_tmp_settings()).get("/note/prior").get_json()["submissions"] == []
    other = dict(UPLOADED_IMG_1698, invoice_filename="IMG_9999.pdf")
    assert _client(_tmp_settings(), other).get("/note/prior").get_json()["submissions"] == []


def test_the_note_downloads_as_a_named_pdf_with_the_receipt_header():
    _sheet(prior=[_line("Sam", "Crayons", "IMG_1698.pdf", "0.53", "10000001-1")])
    r = _client(_tmp_settings(), UPLOADED_IMG_1698).get("/note.pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf"
    assert "IMG_1698 - earlier submissions.pdf" in r.headers["Content-Disposition"]
    text = _pdf_text(r.data)
    assert "Walmart" in text and "$87.36" in text and "Reimbursement 10000001" in text


def test_there_is_no_note_for_a_receipt_never_submitted():
    _sheet()
    assert _client(_tmp_settings(), UPLOADED_IMG_1698).get("/note.pdf").status_code == 404


def test_a_sheet_error_is_reported_not_shown_as_no_earlier_submissions():
    def _broken():
        raise RuntimeError("token expired")
    sheets_logger._get_service = _broken
    r = _client(_tmp_settings(), UPLOADED_IMG_1698).get("/note/prior")
    assert r.status_code == 502 and "token expired" in r.get_json()["error"]


def test_the_students_page_saves_and_shows_the_ids():
    settings = _tmp_settings()
    client = _client(settings)
    r = client.post("/students", json={"students": [{"name": "Sam", "student_id": "1234567"},
                                                    {"name": "", "student_id": ""}]})
    assert r.get_json()["students"] == [{"name": "Sam", "student_id": "1234567"}]
    page = client.get("/students").data.decode()
    assert 'value="Sam"' in page and 'value="1234567"' in page


def test_the_students_page_refuses_a_duplicate_child():
    r = _client(_tmp_settings()).post("/students", json={"students": [
        {"name": "Sam", "student_id": "1"}, {"name": "SAM", "student_id": "2"}]})
    assert r.status_code == 400 and "twice" in r.get_json()["error"]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def test_the_confirm_page_checks_for_earlier_submissions_and_offers_the_note():
    page = (ROOT / "templates" / "confirm.html").read_text()
    assert "fetch('/note/prior')" in page
    assert 'href="/note.pdf"' in page
    assert "esc(s.student)" in page          # names are escaped, not injected raw


def test_the_home_page_links_to_the_students_page():
    assert 'href="/students"' in (ROOT / "templates" / "index.html").read_text()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} tests passed; shared receipts carry a note for the next child.")

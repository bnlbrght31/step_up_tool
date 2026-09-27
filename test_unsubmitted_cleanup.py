"""
Tests for the Unsubmitted-tab cleanup that runs after a submission is logged.

The Unsubmitted tab stages Amazon orders that haven't been reimbursed yet. Once
an order is submitted it should leave that tab -- but only when the user says so,
because a single order is often submitted separately for each child.

These run against a fake Sheets service, so they never touch the live workbook.

Run: python test_unsubmitted_cleanup.py   (or: pytest test_unsubmitted_cleanup.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fake_sheets import FakeSheets
from src import sheets_logger


UNSUBMITTED_HEADER = ["Student", "Item", "Store", "Order/Receipt #", "Price",
                      "Date Purchased", "Status"]


def _fake(extra_rows=None, status=""):
    rows = [
        UNSUBMITTED_HEADER,
        # short row, no Status cell -- exactly how the live sheet stores these
        ["", "Runtoo Kids Wall Decals", "Amazon", "111-7705354-6743464", "18.99", "2025-07-11"],
        ["", "TMNT Michelangelo", "Amazon", "111-7468621-1016217", "45.99", "2026-06-09"] + ([status] if status else []),
        ["", "Brick Loot Soccer Balls", "Amazon", "111-5192806-4273051", "15.92", "2026-06-23"],
        # Hand-entered non-Amazon rows: the reference is whatever the user pasted.
        ["", "School supplies", "Target", "Target 8-14-26", "154.41", "2026-08-14"],
        ["", "Internet Aug", "AT&T", "ATT-AUG-2026", "50.18", "2026-08-06"],
    ]
    rows.extend(extra_rows or [])
    svc = FakeSheets({"Unsubmitted": rows, "2026-2027 Line Items": [sheets_logger.TESTING_HEADER]})
    sheets_logger._get_service = lambda: svc
    return svc


TARGET = "111-7468621-1016217"


# ---------------------------------------------------------------------------
# Deriving the order number from the uploaded invoice filename
# ---------------------------------------------------------------------------

def test_reference_parsed_from_amazon_invoice_filename():
    assert sheets_logger.reference_from_invoice("111-7468621-1016217.pdf") == TARGET


def test_reference_parsed_from_any_vendors_filename():
    """Any receipt can carry a reference now, not just Amazon orders."""
    assert sheets_logger.reference_from_invoice("Target 8-14-26.pdf") == "Target 8-14-26"
    assert sheets_logger.reference_from_invoice("ATT-AUG-2026.pdf") == "ATT-AUG-2026"


def test_reference_is_empty_when_there_is_no_filename():
    for name in ("", "   ", ".pdf", None):
        assert sheets_logger.reference_from_invoice(name) == "", repr(name)


# ---------------------------------------------------------------------------
# Finding the staged row
# ---------------------------------------------------------------------------

def test_find_unsubmitted_row_returns_matching_row():
    _fake()
    row = sheets_logger.find_unsubmitted_row(TARGET)
    assert row is not None
    assert row["row_index"] == 3          # 1-based, header is row 1
    assert row["item"] == "TMNT Michelangelo"
    assert row["price"] == "45.99"
    assert row["date_purchased"] == "2026-06-09"
    assert row["status"] == ""            # short row padded, not IndexError


def test_find_unsubmitted_row_returns_none_when_absent():
    _fake()
    assert sheets_logger.find_unsubmitted_row("111-0000000-0000000") is None


def test_find_matches_a_hand_entered_non_amazon_reference():
    _fake()
    row = sheets_logger.find_unsubmitted_row("Target 8-14-26")
    assert row is not None
    assert row["item"] == "School supplies"
    assert row["store"] == "Target"


def test_find_treats_underscores_and_spaces_as_the_same():
    """secure_filename() turns "Target 8-14-26.pdf" into "Target_8-14-26.pdf"."""
    _fake()
    ref = sheets_logger.reference_from_invoice("Target_8-14-26.pdf")
    assert sheets_logger.find_unsubmitted_row(ref)["item"] == "School supplies"


def test_find_ignores_case_and_surrounding_whitespace():
    _fake()
    assert sheets_logger.find_unsubmitted_row("  att-aug-2026 ")["store"] == "AT&T"


def test_find_does_not_match_an_unrelated_filename():
    _fake()
    assert sheets_logger.find_unsubmitted_row("costco-membership") is None


def test_find_does_not_match_on_a_partial_reference():
    """Exact match only -- "Target" must not reach the "Target 8-14-26" row."""
    _fake()
    assert sheets_logger.find_unsubmitted_row("Target") is None


def test_find_unsubmitted_row_reads_back_an_existing_partial_note():
    _fake(status="partial: Alex 10000001 (09/05)")
    row = sheets_logger.find_unsubmitted_row(TARGET)
    assert row["status"] == "partial: Alex 10000001 (09/05)"


# ---------------------------------------------------------------------------
# Removing the staged row
# ---------------------------------------------------------------------------

def test_delete_removes_only_the_matching_row():
    svc = _fake()
    assert sheets_logger.delete_unsubmitted_row(TARGET) is True
    remaining = [r[3] for r in svc.tabs["Unsubmitted"][1:]]
    assert TARGET not in remaining
    assert remaining == ["111-7705354-6743464", "111-5192806-4273051",
                         "Target 8-14-26", "ATT-AUG-2026"]


def test_delete_refuses_when_order_number_is_ambiguous():
    """Two rows for one order means we can't tell which to drop -- don't guess."""
    dupe = ["", "TMNT Michelangelo", "Amazon", TARGET, "45.99", "2026-06-09"]
    svc = _fake(extra_rows=[dupe])
    try:
        sheets_logger.delete_unsubmitted_row(TARGET)
    except ValueError as e:
        assert TARGET in str(e)
    else:
        raise AssertionError("expected ValueError on ambiguous match")
    assert svc.deletions() == [], "must not delete anything when ambiguous"
    assert len(svc.tabs["Unsubmitted"]) == 7


def test_delete_is_a_noop_when_order_is_already_gone():
    svc = _fake()
    assert sheets_logger.delete_unsubmitted_row("111-0000000-0000000") is False
    assert svc.deletions() == []
    assert len(svc.tabs["Unsubmitted"]) == 6


# ---------------------------------------------------------------------------
# Keeping the row, but recording which child was submitted
# ---------------------------------------------------------------------------

def test_mark_partial_stamps_the_status_column():
    svc = _fake()
    note = sheets_logger.mark_unsubmitted_partial(TARGET, "Alex", "10000001")
    assert note.startswith("partial: Alex 10000001")
    assert svc.tabs["Unsubmitted"][2][6] == note
    assert svc.deletions() == [], "keeping a row must never delete it"


def test_mark_partial_appends_a_second_child():
    svc = _fake()
    sheets_logger.mark_unsubmitted_partial(TARGET, "Alex", "10000001")
    note = sheets_logger.mark_unsubmitted_partial(TARGET, "Sam", "10000002")
    assert "Alex 10000001" in note
    assert "Sam 10000002" in note
    assert note.count("partial:") == 2


def test_mark_partial_does_not_duplicate_the_same_submission():
    """Re-clicking 'Keep it' for the same child must not stack up notes."""
    _fake()
    first = sheets_logger.mark_unsubmitted_partial(TARGET, "Alex", "10000001")
    again = sheets_logger.mark_unsubmitted_partial(TARGET, "Alex", "10000001")
    assert again == first


def test_mark_partial_is_a_noop_when_order_is_absent():
    svc = _fake()
    assert sheets_logger.mark_unsubmitted_partial("111-0000000-0000000", "Sam", "1") == ""
    assert svc.updates == []


# ---------------------------------------------------------------------------
# Regression guard for the bug that started all this
# ---------------------------------------------------------------------------

def test_logging_a_submission_never_touches_the_unsubmitted_tab():
    """Removal happens ONLY on an explicit click, never as a side effect of logging.

    The inverse bug (auto-removing on log) would silently drop a row the user
    still needs for another child.
    """
    svc = _fake()
    before = [list(r) for r in svc.tabs["Unsubmitted"]]
    sheets_logger.log_submission_to_testing(
        "Alex", "10000001",
        [{"cost": "45.99", "tax": "0", "description": "TMNT Michelangelo",
          "vendor": "Amazon", "purchase_date": "06/09/2026"}],
        f"{TARGET}.pdf",
    )
    assert svc.tabs["Unsubmitted"] == before
    assert svc.deletions() == []
    assert svc.updates == []




# ---------------------------------------------------------------------------
# Flask wiring
# ---------------------------------------------------------------------------

def _client():
    """A Flask app carrying only the submission blueprint.

    Deliberately does NOT import main, which pulls in Playwright and an Anthropic
    client at module load -- neither has anything to do with these routes.
    """
    from flask import Flask
    from src.submission_routes import bp

    app = Flask(__name__, template_folder="../templates")
    app.secret_key = "test"
    app.config["TESTING"] = True
    app.register_blueprint(bp)
    return app, app.test_client()


def test_log_submission_reports_the_staged_order_for_confirmation():
    """The response carries the staged row so the page can offer Remove/Keep."""
    _fake()
    main, c = _client()
    with c.session_transaction() as s:
        s["invoice_filename"] = f"{TARGET}.pdf"
    r = c.post("/log-submission", json={
        "student": "Alex", "sufs_id": "10000001",
        "items": [{"include": True, "cost": "45.99", "tax": "0",
                   "description": "TMNT", "vendor": "Amazon",
                   "purchase_date": "06/09/2026"}],
    })
    body = r.get_json()
    assert body["success"] is True
    assert body["unsubmitted"]["order_number"] == TARGET
    assert body["unsubmitted"]["item"] == "TMNT Michelangelo"


def test_log_submission_reports_nothing_for_an_unmatched_receipt():
    _fake()
    main, c = _client()
    with c.session_transaction() as s:
        s["invoice_filename"] = "target-receipt.pdf"
    r = c.post("/log-submission", json={
        "student": "Sam", "sufs_id": "10000002",
        "items": [{"include": True, "cost": "10", "tax": "0",
                   "description": "x", "vendor": "Target", "purchase_date": "01/01/2026"}],
    })
    assert r.get_json()["unsubmitted"] is None


def test_remove_route_deletes_the_staged_row():
    svc = _fake()
    main, c = _client()
    r = c.post("/unsubmitted/remove", json={"order_number": TARGET})
    assert r.get_json()["removed"] is True
    assert TARGET not in [row[3] for row in svc.tabs["Unsubmitted"][1:]]


def test_remove_route_reports_an_ambiguous_order_instead_of_guessing():
    dupe = ["", "TMNT Michelangelo", "Amazon", TARGET, "45.99", "2026-06-09"]
    svc = _fake(extra_rows=[dupe])
    main, c = _client()
    r = c.post("/unsubmitted/remove", json={"order_number": TARGET})
    assert r.status_code == 409
    assert "refusing to guess" in r.get_json()["error"]
    assert svc.deletions() == []


def test_remove_route_rejects_an_empty_reference():
    """An empty reference must never reach the delete path."""
    svc = _fake()
    main, c = _client()
    for payload in ({"order_number": ""}, {"order_number": "   "}, {}):
        r = c.post("/unsubmitted/remove", json=payload)
        assert r.status_code == 400, payload
    assert svc.deletions() == []


def test_remove_route_does_not_delete_an_unmatched_reference():
    """A receipt that matches nothing reports back cleanly, touching no rows."""
    svc = _fake()
    main, c = _client()
    r = c.post("/unsubmitted/remove", json={"order_number": "costco-membership"})
    assert r.get_json()["removed"] is False
    assert svc.deletions() == []


def test_remove_route_deletes_a_non_amazon_row():
    svc = _fake()
    main, c = _client()
    r = c.post("/unsubmitted/remove", json={"order_number": "Target_8-14-26"})
    assert r.get_json()["removed"] is True
    assert "Target 8-14-26" not in [row[3] for row in svc.tabs["Unsubmitted"][1:]]


def test_log_submission_reports_a_staged_non_amazon_receipt():
    _fake()
    main, c = _client()
    with c.session_transaction() as s:
        s["invoice_filename"] = "Target_8-14-26.pdf"
    r = c.post("/log-submission", json={
        "student": "Sam", "sufs_id": "10000002",
        "items": [{"include": True, "cost": "154.41", "tax": "0",
                   "description": "School supplies", "vendor": "Target",
                   "purchase_date": "08/14/2026"}],
    })
    assert r.get_json()["unsubmitted"]["item"] == "School supplies"


def test_keep_route_stamps_the_status_and_keeps_the_row():
    svc = _fake()
    main, c = _client()
    r = c.post("/unsubmitted/mark", json={
        "order_number": TARGET, "student": "Alex", "sufs_id": "10000001"})
    assert "Alex 10000001" in r.get_json()["status"]
    assert TARGET in [row[3] for row in svc.tabs["Unsubmitted"][1:]]
    assert svc.deletions() == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} tests passed; Unsubmitted rows leave only on an explicit click.")

"""
Tests for the receipts folder review: finding receipts in the year's folder that
aren't submitted or staged, and staging them in the Unsubmitted tab.

Every test uses a temporary folder, the FakeSheets service and a stubbed
receipt parser, so none touches the real folder, sheet or Claude API.

Run: python test_receipt_folder.py   (or: pytest test_receipt_folder.py)
"""

import io
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image, ImageDraw
from werkzeug.utils import secure_filename
import pdfplumber

from fake_sheets import FakeSheets
from src import receipt_folder as rf
from src import sheets_logger
from src.models import LineItem


@contextmanager
def _folder(files: dict):
    """A temporary receipts folder. `files` maps a relative name to bytes or a PIL image."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, Image.Image):
                content.save(path)
            else:
                path.write_bytes(content)
        yield root


def _photo(w: int = 400, h: int = 300) -> Image.Image:
    im = Image.new("RGB", (w, h), "white")
    ImageDraw.Draw(im).rectangle([20, 20, w // 2, h // 3], fill=(30, 30, 30))
    return im


PDF = b"%PDF-1.4 placeholder"


# ---------------------------------------------------------------------------
# Grouping and classification
# ---------------------------------------------------------------------------

def test_a_photo_and_its_pdf_are_one_receipt():
    with _folder({"IMG_1.jpeg": _photo(), "IMG_1.pdf": PDF}) as root:
        receipts = rf.review(root, set(), set())
    assert len(receipts) == 1
    assert receipts[0].reference == "IMG_1"
    assert receipts[0].kind == "photo+pdf"


def test_kinds_for_pdf_only_and_photo_only():
    with _folder({"a.pdf": PDF, "IMG_2.png": _photo()}) as root:
        kinds = {r.reference: r.kind for r in rf.review(root, set(), set())}
    assert kinds == {"a": "pdf", "IMG_2": "photo"}


def test_uppercase_extensions_are_handled_like_lowercase():
    with _folder({"IMG_3.JPG": _photo(), "b.PDF": PDF}) as root:
        kinds = {r.reference: r.kind for r in rf.review(root, set(), set())}
    assert kinds == {"IMG_3": "photo", "b": "pdf"}


def test_subfolders_and_hidden_files_are_ignored():
    with _folder({"a.pdf": PDF, ".DS_Store": b"x",
                  "Originals/IMG_1.jpeg": _photo(), "Not submitting/c.pdf": PDF}) as root:
        refs = [r.reference for r in rf.review(root, set(), set())]
    assert refs == ["a"]


def test_unsupported_files_are_listed_with_a_reason():
    with _folder({"notes.docx": b"x"}) as root:
        [receipt] = rf.review(root, set(), set())
    assert receipt.status == "unsupported"
    assert ".docx" in receipt.reason


def test_classification_prefers_submitted_then_staged():
    with _folder({"a.pdf": PDF, "b.pdf": PDF, "c.pdf": PDF}) as root:
        status = {r.reference: r.status for r in rf.review(root, {"a"}, {"a", "b"})}
    assert status == {"a": "submitted", "b": "staged", "c": "untracked"}


def test_find_receipt_matches_by_normalised_name_and_never_by_path():
    with _folder({"Target 8-14-26.pdf": PDF}) as root:
        assert rf.find_receipt(root, "target_8-14-26").reference == "Target 8-14-26"
        assert rf.find_receipt(root, "../../etc/passwd") is None
        assert rf.find_receipt(root, "") is None


# ---------------------------------------------------------------------------
# Converting photos to PDF
# ---------------------------------------------------------------------------

# A PDF page's size in points for an image of `px` pixels at PDF_DPI.
def _pts(px: int) -> int:
    return round(px * 72 / rf.PDF_DPI)


def _page_size(pdf_path: Path) -> tuple[int, int]:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        return round(page.width), round(page.height)


def _phone_photo() -> Image.Image:
    """A 24 MP, 4284x5712 'photo' with noise, harder to compress than a real receipt."""
    im = Image.effect_noise((4284, 5712), 12).point(lambda v: min(255, v + 90)).convert("RGB")
    draw = ImageDraw.Draw(im)
    for y in range(300, 5400, 90):
        draw.rectangle([600, y, 600 + (y * 37) % 2800 + 400, y + 30], fill=(30, 30, 30))
    return im


def test_a_phone_photo_becomes_a_pdf_under_1_mb_with_a_2200px_long_edge():
    with _folder({"IMG_1.jpeg": _phone_photo()}) as root:
        pdf = rf.to_pdf(root / "IMG_1.jpeg")
        assert pdf == root / "IMG_1.pdf"
        assert pdf.stat().st_size < 1_000_000, f"{pdf.stat().st_size} bytes"
        assert max(_page_size(pdf)) == _pts(2200)


def test_phone_rotation_is_applied():
    im = Image.new("RGB", (3000, 2000), "white")      # stored landscape
    exif = Image.Exif()
    exif[0x0112] = 6                                   # "rotate 90° to display": portrait
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif)
    with _folder({"IMG_2.jpeg": buf.getvalue()}) as root:
        width, height = _page_size(rf.to_pdf(root / "IMG_2.jpeg"))
    assert height > width
    assert height == _pts(2200)


def test_a_small_image_is_not_upscaled():
    with _folder({"IMG_3.png": _photo(400, 300)}) as root:
        assert _page_size(rf.to_pdf(root / "IMG_3.png")) == (_pts(400), _pts(300))


def test_heic_and_uppercase_extensions_convert():
    with _folder({"IMG_4.HEIC": _photo(), "IMG_5.JPG": _photo()}) as root:
        for name, expected in (("IMG_4.HEIC", "IMG_4.pdf"), ("IMG_5.JPG", "IMG_5.pdf")):
            pdf = rf.to_pdf(root / name)
            assert pdf.name == expected
            assert pdf.read_bytes().startswith(b"%PDF")


def test_an_existing_pdf_is_never_overwritten():
    with _folder({"IMG_6.jpeg": _photo(), "IMG_6.pdf": b"%PDF mine"}) as root:
        try:
            rf.to_pdf(root / "IMG_6.jpeg")
        except rf.ConversionError:
            pass
        else:
            raise AssertionError("expected ConversionError")
        assert (root / "IMG_6.pdf").read_bytes() == b"%PDF mine"


def test_a_corrupt_image_raises_and_leaves_no_pdf():
    with _folder({"IMG_7.jpeg": b"not an image"}) as root:
        try:
            rf.to_pdf(root / "IMG_7.jpeg")
        except rf.ConversionError as e:
            assert "IMG_7.jpeg" in str(e)
        else:
            raise AssertionError("expected ConversionError")
        assert not (root / "IMG_7.pdf").exists()


# ---------------------------------------------------------------------------
# Moving files
# ---------------------------------------------------------------------------

def test_move_into_creates_the_subfolder_and_moves_every_file():
    with _folder({"a.pdf": PDF, "a.jpeg": b"jpeg"}) as root:
        moved = rf.move_into(root, rf.NOT_SUBMITTING, [root / "a.pdf", root / "a.jpeg"])
        assert sorted(p.name for p in moved) == ["a.jpeg", "a.pdf"]
        assert all(p.parent == root / rf.NOT_SUBMITTING for p in moved)
        assert not (root / "a.pdf").exists() and not (root / "a.jpeg").exists()


def test_move_into_never_overwrites_a_file_already_there():
    with _folder({"IMG_1.jpeg": b"new", "Originals/IMG_1.jpeg": b"old",
                  "Originals/IMG_1 (2).jpeg": b"older"}) as root:
        [moved] = rf.move_into(root, rf.ORIGINALS, [root / "IMG_1.jpeg"])
        assert moved.name == "IMG_1 (3).jpeg"
        assert moved.read_bytes() == b"new"
        assert (root / "Originals" / "IMG_1.jpeg").read_bytes() == b"old"


# ---------------------------------------------------------------------------
# Unsubmitted row from a parsed receipt
# ---------------------------------------------------------------------------

def _item(desc="Crayons", vendor="Walmart", date="07/23/2026"):
    return LineItem(description=desc, vendor=vendor, purchase_date=date, cost=1.0)


def test_row_uses_the_first_item_and_the_receipt_total():
    row = rf.row_from_parse("IMG_1", [_item()], {"grand_total": 87.36, "computed_total": 87.35})
    assert row == ["", "Crayons", "Walmart", "IMG_1", "87.36", "07/23/2026", ""]


def test_row_counts_the_other_items():
    row = rf.row_from_parse("IMG_1", [_item(), _item("Rulers"), _item("Notebook")], {"grand_total": 10})
    assert row[1] == "Crayons + 2 more"


def test_row_falls_back_to_the_computed_total():
    row = rf.row_from_parse("IMG_1", [_item()], {"grand_total": None, "computed_total": 12.5})
    assert row[4] == "12.50"


def test_row_for_an_unread_receipt_has_only_the_reference():
    assert rf.row_from_parse("IMG_1", [], None) == ["", "", "", "IMG_1", "", "", ""]


# ---------------------------------------------------------------------------
# Sheet access
# ---------------------------------------------------------------------------

def _sheet(staged=(), submitted=(), include_current_tab=True):
    """FakeSheets with Unsubmitted rows staged under `staged` references and Line
    Items rows whose Invoice column holds `submitted` file names."""
    tabs = {"Unsubmitted": [sheets_logger.UNSUBMITTED_HEADER]
            + [["", "item", "Store", ref, "1.00", "08/01/2026", ""] for ref in staged]}
    prior, current = sheets_logger.LINE_ITEMS_TABS[0], sheets_logger.LINE_ITEMS_TABS[-1]
    tabs[prior] = [sheets_logger.TESTING_HEADER] + [
        ["Sam", "item", "Store", name, "1.00", "08/01/2026", "submitted", "10000001-1"]
        for name in submitted]
    if include_current_tab and current != prior:
        tabs[current] = [sheets_logger.TESTING_HEADER]
    svc = FakeSheets(tabs)
    sheets_logger._get_service = lambda: svc
    return svc


class _FailingSheets(FakeSheets):
    """Every value read fails, as with an expired credential or no network."""

    def get(self, spreadsheetId=None, range=None, **kw):
        if range is not None:
            raise RuntimeError("503 Service Unavailable")
        return super().get(spreadsheetId=spreadsheetId, range=range, **kw)


def test_append_unsubmitted_appends_rows_as_given():
    svc = _sheet()
    row = ["", "Crayons", "Walmart", "IMG_1", "87.36", "07/23/2026", ""]
    sheets_logger.append_unsubmitted([row])
    assert svc.tabs["Unsubmitted"][-1] == row


def test_append_orders_still_stages_amazon_orders_the_same_way():
    svc = _sheet()
    sheets_logger.append_orders([{"description": "Workbook", "order_number": "111-0000001-0000001",
                                  "total": "9.99", "purchase_date": "2026-08-01"}])
    assert svc.tabs["Unsubmitted"][-1] == ["", "Workbook", "Amazon", "111-0000001-0000001",
                                           "9.99", "2026-08-01", ""]


def test_tracked_references_are_normalised_file_names():
    _sheet(staged=["Target 8-14-26"], submitted=["IMG_7.pdf", "111-0000001-0000001.pdf"])
    submitted, staged = sheets_logger.read_tracked_references()
    assert submitted == {"img 7", "111-0000001-0000001"}
    assert staged == {"target 8-14-26"}


def test_a_photo_submitted_as_a_pdf_is_classified_submitted():
    _sheet(submitted=["IMG_7.pdf"])
    submitted, staged = sheets_logger.read_tracked_references()
    with _folder({"IMG_7.jpeg": _photo()}) as root:
        [receipt] = rf.review(root, submitted, staged)
    assert receipt.status == "submitted"


def test_a_line_items_tab_that_doesnt_exist_yet_is_not_an_error():
    _sheet(submitted=["IMG_7.pdf"], include_current_tab=False)
    submitted, _ = sheets_logger.read_tracked_references()
    assert submitted == {"img 7"}


def test_a_failed_sheet_read_raises_instead_of_returning_nothing():
    """Swallowing the error would make every receipt look untracked."""
    tabs = {"Unsubmitted": [sheets_logger.UNSUBMITTED_HEADER],
            sheets_logger.LINE_ITEMS_TABS[0]: [sheets_logger.TESTING_HEADER]}
    sheets_logger._get_service = lambda: _FailingSheets(tabs)
    try:
        sheets_logger.read_tracked_references()
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the read error to propagate")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _client(root, parse=None):
    """A test client whose routes read `root` and use a stubbed receipt parser."""
    from flask import Flask
    from src import receipt_routes

    receipt_routes.receipts_folder = lambda: root
    receipt_routes._parse = parse or (lambda pdf: ([_item()], 0.0213, {"grand_total": 87.36}))
    app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))
    app.register_blueprint(receipt_routes.bp)
    return app.test_client()


def _raise(*_):
    raise RuntimeError("Claude unavailable")


def test_review_lists_each_receipt_with_its_status():
    _sheet(staged=["b"], submitted=["c.pdf"])
    with _folder({"a.pdf": PDF, "b.pdf": PDF, "c.pdf": PDF}) as root:
        data = _client(root).get("/receipts/review").get_json()
    assert {r["reference"]: r["status"] for r in data["receipts"]} == {
        "a": "untracked", "b": "staged", "c": "submitted"}


def test_review_reports_a_sheet_error_instead_of_listing_receipts():
    sheets_logger._get_service = lambda: _FailingSheets(
        {"Unsubmitted": [sheets_logger.UNSUBMITTED_HEADER]})
    with _folder({"a.pdf": PDF}) as root:
        r = _client(root).get("/receipts/review")
    assert r.status_code == 502
    assert "receipts" not in r.get_json()


def test_review_reports_a_missing_folder_clearly():
    _sheet()
    with _folder({}) as root:
        r = _client(root / "2027-2028").get("/receipts/review")
    assert r.status_code == 404
    assert "2027-2028" in r.get_json()["error"]


def test_add_converts_a_photo_stages_it_and_moves_the_photo():
    svc = _sheet()
    with _folder({"IMG_1.jpeg": _photo()}) as root:
        data = _client(root).post("/receipts/add", json={"reference": "IMG_1"}).get_json()
        assert data["status"] == "added" and data["converted"] and not data["needs_details"]
        assert (root / "IMG_1.pdf").exists()
        assert (root / "Originals" / "IMG_1.jpeg").exists() and not (root / "IMG_1.jpeg").exists()
    assert svc.tabs["Unsubmitted"][-1] == ["", "Crayons", "Walmart", "IMG_1", "87.36", "07/23/2026", ""]
    assert data["row"]["Store"] == "Walmart"


def test_adding_the_same_receipt_twice_stages_it_once():
    svc = _sheet()
    with _folder({"a.pdf": PDF}) as root:
        client = _client(root)
        client.post("/receipts/add", json={"reference": "a"})
        second = client.post("/receipts/add", json={"reference": "a"}).get_json()
    assert second["status"] == "already_tracked"
    assert len(svc.appends) == 1


def test_an_unreadable_receipt_is_still_staged_with_its_name():
    svc = _sheet()
    with _folder({"a.pdf": PDF}) as root:
        data = _client(root, parse=_raise).post("/receipts/add", json={"reference": "a"}).get_json()
    assert data["status"] == "added" and data["needs_details"]
    assert svc.tabs["Unsubmitted"][-1] == ["", "", "", "a", "", "", ""]


def test_a_failed_conversion_stages_nothing_and_moves_nothing():
    svc = _sheet()
    with _folder({"IMG_2.jpeg": b"not an image"}) as root:
        r = _client(root).post("/receipts/add", json={"reference": "IMG_2"})
        assert r.status_code == 422
        assert (root / "IMG_2.jpeg").exists() and not (root / "Originals").exists()
    assert svc.appends == []


def test_a_failed_sheet_write_leaves_the_photo_in_place():
    class _NoAppend(FakeSheets):
        def append(self, *a, **kw):
            raise RuntimeError("quota exceeded")
    tabs = {"Unsubmitted": [sheets_logger.UNSUBMITTED_HEADER]}
    sheets_logger._get_service = lambda: _NoAppend(tabs)
    with _folder({"IMG_3.jpeg": _photo()}) as root:
        r = _client(root).post("/receipts/add", json={"reference": "IMG_3"})
        assert r.status_code == 500
        assert (root / "IMG_3.jpeg").exists()


def test_two_photos_and_no_pdf_converts_the_first_and_moves_both():
    _sheet()
    with _folder({"IMG_4.jpeg": _photo(), "IMG_4.png": _photo()}) as root:
        _client(root).post("/receipts/add", json={"reference": "IMG_4"})
        assert (root / "IMG_4.pdf").exists()
        assert sorted(p.name for p in (root / "Originals").iterdir()) == ["IMG_4.jpeg", "IMG_4.png"]


def test_names_with_apostrophes_and_spaces_can_be_added():
    svc = _sheet()
    with _folder({"Bob's receipt.pdf": PDF}) as root:
        data = _client(root).post("/receipts/add", json={"reference": "Bob's receipt"}).get_json()
    assert data["status"] == "added"
    assert svc.tabs["Unsubmitted"][-1][3] == "Bob's receipt"


def test_skip_moves_an_untracked_receipt_to_not_submitting():
    _sheet()
    with _folder({"a.pdf": PDF, "a.jpeg": b"jpeg"}) as root:
        data = _client(root).post("/receipts/skip", json={"reference": "a"}).get_json()
        assert sorted(data["moved"]) == ["a.jpeg", "a.pdf"]
        assert (root / "Not submitting" / "a.pdf").exists()


def test_skip_refuses_a_staged_receipt():
    _sheet(staged=["a"])
    with _folder({"a.pdf": PDF}) as root:
        r = _client(root).post("/receipts/skip", json={"reference": "a"})
        assert r.status_code == 409
        assert (root / "a.pdf").exists()


def test_paths_and_unknown_names_are_rejected_without_moving_anything():
    svc = _sheet()
    with _folder({"a.pdf": PDF}) as root:
        client = _client(root)
        for route in ("/receipts/skip", "/receipts/add"):
            for ref in ("../../etc/passwd", "nope", ""):
                assert client.post(route, json={"reference": ref}).status_code == 404, (route, ref)
        assert [p.name for p in root.iterdir()] == ["a.pdf"]
    assert svc.appends == []


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

TEMPLATES = Path(__file__).parent / "templates"


def test_the_page_renders_with_the_folder_path():
    with _folder({}) as root:
        r = _client(root).get("/receipts")
    assert r.status_code == 200
    assert b"Review receipts folder" in r.data
    assert str(root).encode() in r.data


def test_a_second_add_cannot_start_while_a_batch_runs():
    page = (TEMPLATES / "receipts.html").read_text()
    assert "if (running) return;" in page
    assert "addBtn.disabled = true;" in page


def test_receipt_names_are_escaped_and_sent_as_json():
    page = (TEMPLATES / "receipts.html").read_text()
    assert "esc(r.reference)" in page
    assert "JSON.stringify(body)" in page


def test_the_home_page_links_to_the_review():
    assert 'href="/receipts"' in (TEMPLATES / "index.html").read_text()


# ---------------------------------------------------------------------------
# Names the upload page sanitises
# ---------------------------------------------------------------------------
# /upload stores secure_filename(name) as the Invoice, dropping apostrophes,
# brackets and accents; the folder and hand-typed sheet rows keep them.

SANITISED = ["Bob's receipt.pdf", "Lowe's 8-1-26.pdf", "Target (2).pdf", "Café.pdf"]


def test_a_submitted_receipt_matches_even_when_the_upload_renamed_it():
    _sheet(submitted=[secure_filename(n) for n in SANITISED])
    submitted, staged = sheets_logger.read_tracked_references()
    with _folder({n: PDF for n in SANITISED}) as root:
        status = {r.reference: r.status for r in rf.review(root, submitted, staged)}
    assert set(status.values()) == {"submitted"}, status


def test_the_remove_prompt_finds_a_row_staged_under_its_original_name():
    _sheet(staged=["Lowe's 8-1-26"])
    uploaded = sheets_logger.reference_from_invoice(secure_filename("Lowe's 8-1-26.pdf"))
    assert sheets_logger.find_unsubmitted_row(uploaded) is not None


# ---------------------------------------------------------------------------
# Skip and add racing on the same receipt
# ---------------------------------------------------------------------------

def test_a_skip_during_an_add_never_leaves_a_row_for_a_skipped_receipt():
    """Not submitting clicked just before Add sends both requests at once (the
    app serves requests on threads). Whichever wins, the receipt must not end up
    both staged in the sheet and moved to Not submitting."""
    import threading

    svc = _sheet()
    add_is_reading, release_add = threading.Event(), threading.Event()

    def slow_parse(pdf):
        add_is_reading.set()
        release_add.wait(5)
        return [_item()], 0.0, {"grand_total": 1.0}

    with _folder({"a.pdf": PDF}) as root:
        adding = _client(root, parse=slow_parse)
        skipping = adding.application.test_client()
        status = {}
        adder = threading.Thread(target=lambda: status.setdefault(
            "add", adding.post("/receipts/add", json={"reference": "a"}).status_code))
        skipper = threading.Thread(target=lambda: status.setdefault(
            "skip", skipping.post("/receipts/skip", json={"reference": "a"}).status_code))
        adder.start()
        assert add_is_reading.wait(5), "add never reached the receipt read"
        skipper.start()
        skipper.join(0.5)          # an unguarded skip completes in this window
        release_add.set()
        adder.join(5)
        skipper.join(5)
        skipped = (root / "Not submitting" / "a.pdf").exists()
    staged = len(svc.appends) == 1
    assert staged != skipped, f"staged={staged} skipped={skipped} {status}"


def test_the_page_locks_a_row_before_its_skip_request_returns():
    page = (TEMPLATES / "receipts.html").read_text()
    skip_fn = page[page.index("async function skip("):page.index("async function addSelected(")]
    assert skip_fn.index("lockRow(i)") < skip_fn.index("await post('/receipts/skip'")
    assert "if (running || pendingSkips) return;" in page


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} tests passed; every receipt in the folder is accounted for.")

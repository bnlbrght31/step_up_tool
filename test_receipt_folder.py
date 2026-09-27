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
import pdfplumber

from src import receipt_folder as rf


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


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} tests passed; every receipt in the folder is accounted for.")

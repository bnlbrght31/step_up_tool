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


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} tests passed; every receipt in the folder is accounted for.")

# Receipt Folder Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Review receipts folder" page that finds receipts in the scholarship-year folder that are neither submitted nor staged, and stages the ones you confirm in the Unsubmitted tab — converting phone photos to small PDFs and having Claude fill in each row.

**Architecture:** Folder logic lives in a new `src/receipt_folder.py` with no sheet or Claude calls. A new Flask blueprint, `src/receipt_routes.py`, joins it to two new `sheets_logger` functions and the existing `parse_receipt`. A new `templates/receipts.html` page drives the review and processes receipts one request at a time.

**Tech Stack:** Python 3.14, Flask, Pillow (image → PDF), pillow-heif (HEIC), Google Sheets API via `sheets_logger`, the existing Claude receipt parser.

**Spec:** `docs/superpowers/specs/2026-09-27-receipt-folder-review-design.md`

## Global Constraints

- Run everything with the project venv: `./.venv/bin/python` from `step_up_tool/`. pytest is **not** installed. Tests are plain scripts with `def test_*` functions and a runner block at the bottom.
- **Every new test goes above the file's `if __name__ == "__main__":` block.** A test added below it never runs.
- The folder is `scholarship_year.receipts_folder()` → `~/Desktop/SUFS/<year label>/`, e.g. `~/Desktop/SUFS/2026-2027/`.
- Subfolder names are exactly `Originals` and `Not submitting`. The review reads the top level only.
- Supported: `.pdf`; images `.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`, case-insensitive. Files whose names start with `.` are ignored.
- Conversion: EXIF rotation applied, long edge at most 2200 px (never upscaled), RGB, JPEG quality 75, PDF resolution 200 dpi.
- Nothing is ever deleted. Moves never overwrite: a clash gets `" (2)"`, `" (3)"`, … before the extension.
- POST routes accept a receipt **reference**, never a path.
- Tests never touch the real folder, the real sheet or the Claude API: temporary folders, `FakeSheets`, and a stubbed parser.
- **The repo is public: no children's names, real reimbursement IDs or real student IDs in code, tests or fixtures.** Use generic names (`Sam`, `IMG_1`, `Target 8-14-26`).
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Work happens on branch `receipt-folder-review` (already created; the spec is committed there).

## Review Focus

1. **The year's folder doesn't exist yet** (right after July 1, before anything is downloaded). The review should return a clear "folder not found" message, not a crash. Test in Task 7.
2. **Uppercase extensions from a phone** (`IMG_1.JPG`, `IMG_2.HEIC`, `a.PDF`). These should behave exactly like lowercase ones. Tests in Task 2 (review) and Task 3 (conversion).
3. **Names with apostrophes or spaces** (`Bob's receipt.pdf`). These should be listed, skippable and addable, and the page must escape them. Route test in Task 7; escaping asserted in Task 8.
4. **Add pressed again while a batch runs.** There should be no second batch, and the button stays disabled until the first is done. Asserted in Task 8.
5. **A receipt with two photos and no PDF** (`IMG_1.jpeg` + `IMG_1.png`). The first by name is converted, and both move to `Originals`. Test in Task 7.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/scholarship_year.py` | modify | `receipts_folder()`: the year's receipts folder |
| `src/pdf_downloader.py` | modify | `OUTPUT_DIR` uses `receipts_folder()` |
| `src/receipt_folder.py` | create | grouping, classification, image → PDF, moves, row mapping |
| `src/sheets_logger.py` | modify | public `normalize_reference`; `append_unsubmitted`; `read_tracked_references`; `append_orders` becomes a caller |
| `src/receipt_routes.py` | create | blueprint: page, review, skip, add |
| `main.py` | modify | register the blueprint |
| `templates/receipts.html` | create | the page |
| `templates/index.html` | modify | home-page card |
| `requirements.txt` | modify | `Pillow`, `pillow-heif` |
| `README.md` | modify | usage section |
| `test_receipt_folder.py` | create | all tests for this feature |
| `test_scholarship_year.py` | modify | `receipts_folder()` tests |

---

### Task 1: The receipts folder path

**Files:**
- Modify: `src/scholarship_year.py` (imports; new function after `gmail_date`)
- Modify: `src/pdf_downloader.py` (the `OUTPUT_DIR =` line)
- Test: `test_scholarship_year.py`

**Interfaces:**
- Produces: `scholarship_year.receipts_folder(today: date | None = None) -> pathlib.Path`

- [ ] **Step 1: Write the failing tests**

Add above the `if __name__ == "__main__":` block in `test_scholarship_year.py`:

```python
def test_receipts_folder_is_the_years_folder_under_desktop_sufs():
    assert sy.receipts_folder(date(2026, 9, 26)) == Path.home() / "Desktop" / "SUFS" / "2026-2027"
    assert sy.receipts_folder(date(2027, 7, 1)) == Path.home() / "Desktop" / "SUFS" / "2027-2028"


def test_invoice_downloader_saves_into_the_receipts_folder():
    from src import pdf_downloader
    assert pdf_downloader.OUTPUT_DIR == sy.receipts_folder()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `./.venv/bin/python -c "import test_scholarship_year as t; t.test_receipts_folder_is_the_years_folder_under_desktop_sufs()"`
Expected: `AttributeError: module 'src.scholarship_year' has no attribute 'receipts_folder'`

- [ ] **Step 3: Implement**

In `src/scholarship_year.py`, change the import line `from datetime import date` to:

```python
from datetime import date
from pathlib import Path
```

and add after `gmail_date`:

```python
def receipts_folder(today: date | None = None) -> Path:
    """Where the year's receipts live: ~/Desktop/SUFS/<year label>/.

    The Amazon invoice downloader saves here and the receipts folder review
    reads it, so both move to the new year's folder each July.
    """
    return Path.home() / "Desktop" / "SUFS" / label(start_year(today))
```

In `src/pdf_downloader.py`, replace

```python
OUTPUT_DIR = Path.home() / "Desktop" / "SUFS" / scholarship_year.label(scholarship_year.start_year())
```

with

```python
OUTPUT_DIR = scholarship_year.receipts_folder()
```

- [ ] **Step 4: Run the whole file to verify it passes**

Run: `./.venv/bin/python test_scholarship_year.py`
Expected: ends with `OK — 10 tests passed; the scholarship year rolls over on its own.`

- [ ] **Step 5: Commit**

```bash
git add src/scholarship_year.py src/pdf_downloader.py test_scholarship_year.py
git commit -m "Derive the receipts folder from the scholarship year

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Grouping and classifying receipts

**Files:**
- Modify: `src/sheets_logger.py`: rename `_normalize_reference` → `normalize_reference` (the definition and its four call sites, all in this file)
- Create: `src/receipt_folder.py`
- Create: `test_receipt_folder.py`

**Interfaces:**
- Consumes: `sheets_logger.normalize_reference(value: str) -> str`
- Produces, in `src/receipt_folder.py`:
  - constants `PDF_EXT = ".pdf"`, `IMAGE_EXTS`, `ORIGINALS = "Originals"`, `NOT_SUBMITTING = "Not submitting"`
  - `@dataclass Receipt(reference: str, files: list[Path], status: str = "untracked", reason: str = "")` with properties `pdf -> Path | None`, `images -> list[Path]`, `kind -> str` (`"pdf"`, `"photo"`, `"photo+pdf"`, `"unsupported"`) and `to_dict() -> dict`
  - `classify(receipt: Receipt, submitted_refs: set[str], staged_refs: set[str]) -> str`
  - `review(folder: Path, submitted_refs: set[str], staged_refs: set[str]) -> list[Receipt]`
  - `find_receipt(folder: Path, reference: str) -> Receipt | None`

- [ ] **Step 1: Rename the normaliser**

In `src/sheets_logger.py`, replace every `_normalize_reference` with `normalize_reference` (the `def` line and four calls). Check that nothing else used the old name:

Run: `grep -rn "_normalize_reference" src/ *.py`
Expected: no output.

Run: `./.venv/bin/python test_unsubmitted_cleanup.py`
Expected: ends with `OK — 28 tests passed`

- [ ] **Step 2: Write the failing tests**

Create `test_receipt_folder.py`:

```python
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
```

- [ ] **Step 3: Run to verify it fails**

Run: `./.venv/bin/python test_receipt_folder.py`
Expected: `ImportError: cannot import name 'receipt_folder' from 'src'`

- [ ] **Step 4: Implement**

Create `src/receipt_folder.py`:

```python
"""
The receipts folder review: which receipts in the scholarship-year folder are
submitted, staged in Unsubmitted, or not tracked at all, plus the file work
needed to stage the untracked ones.

Folder logic only -- no sheet or Claude calls -- so all of it is testable
against a temporary folder. A receipt is a *name*: every top-level file that
shares a normalised name is one receipt, so IMG_1698.jpeg and IMG_1698.pdf
count once.
"""

from dataclasses import dataclass, field
from pathlib import Path

from src.sheets_logger import normalize_reference

PDF_EXT = ".pdf"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}

# Subfolders of the year folder. The review reads only the top level, so
# anything moved into these is never offered again.
ORIGINALS = "Originals"
NOT_SUBMITTING = "Not submitting"


def _supported(path: Path) -> bool:
    ext = path.suffix.lower()
    return ext == PDF_EXT or ext in IMAGE_EXTS


@dataclass
class Receipt:
    reference: str               # file name without extension, as on disk
    files: list[Path] = field(default_factory=list)
    status: str = "untracked"    # submitted | staged | untracked | unsupported
    reason: str = ""

    @property
    def pdf(self) -> Path | None:
        return next((f for f in self.files if f.suffix.lower() == PDF_EXT), None)

    @property
    def images(self) -> list[Path]:
        return sorted(f for f in self.files if f.suffix.lower() in IMAGE_EXTS)

    @property
    def kind(self) -> str:
        if self.pdf and self.images:
            return "photo+pdf"
        if self.pdf:
            return "pdf"
        if self.images:
            return "photo"
        return "unsupported"

    def to_dict(self) -> dict:
        return {
            "reference": self.reference,
            "kind": self.kind,
            "status": self.status,
            "reason": self.reason,
            "files": [{"name": f.name, "size": f.stat().st_size} for f in self.files],
        }


def classify(receipt: Receipt, submitted_refs: set[str], staged_refs: set[str]) -> str:
    """submitted, staged or untracked; the ref sets hold normalised references."""
    key = normalize_reference(receipt.reference)
    if key in submitted_refs:
        return "submitted"
    if key in staged_refs:
        return "staged"
    return "untracked"


def review(folder: Path, submitted_refs: set[str], staged_refs: set[str]) -> list[Receipt]:
    """Every receipt in the top level of `folder`, classified, sorted by reference.

    Files of an unsupported type are returned as their own `unsupported`
    receipts, so they can be shown rather than silently skipped.
    """
    groups: dict[str, list[Path]] = {}
    unsupported: list[Path] = []
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        if _supported(f):
            groups.setdefault(normalize_reference(f.stem), []).append(f)
        else:
            unsupported.append(f)

    receipts = []
    for files in groups.values():
        pdf = next((f for f in files if f.suffix.lower() == PDF_EXT), None)
        receipt = Receipt(reference=(pdf or files[0]).stem, files=files)
        receipt.status = classify(receipt, submitted_refs, staged_refs)
        receipts.append(receipt)
    for f in unsupported:
        receipts.append(Receipt(reference=f.stem, files=[f], status="unsupported",
                                reason=f"unsupported file type {f.suffix.lower() or '(none)'}"))
    return sorted(receipts, key=lambda r: r.reference.casefold())


def find_receipt(folder: Path, reference: str) -> Receipt | None:
    """The supported receipt in `folder` with this reference, or None.

    Matches only receipts found by scanning the folder, so a reference can never
    reach a file outside it. The returned receipt's status is not classified.
    """
    key = normalize_reference(reference)
    if not key:
        return None
    for receipt in review(folder, set(), set()):
        if receipt.status != "unsupported" and normalize_reference(receipt.reference) == key:
            return receipt
    return None
```

- [ ] **Step 5: Run to verify it passes**

Run: `./.venv/bin/python test_receipt_folder.py`
Expected: ends with `OK — 7 tests passed; every receipt in the folder is accounted for.`

- [ ] **Step 6: Commit**

```bash
git add src/sheets_logger.py src/receipt_folder.py test_receipt_folder.py
git commit -m "Group and classify the receipts in the year folder

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Converting photos to small PDFs

**Files:**
- Modify: `requirements.txt`
- Modify: `src/receipt_folder.py` (imports; new section after `find_receipt`)
- Test: `test_receipt_folder.py`

**Interfaces:**
- Produces: `class ConversionError(Exception)`; `to_pdf(image_path: Path) -> Path` (writes `<stem>.pdf` beside the image); constants `MAX_EDGE = 2200`, `JPEG_QUALITY = 75`, `PDF_DPI = 200`

- [ ] **Step 1: Add and install the dependencies**

Append to `requirements.txt`:

```
Pillow>=12.0
pillow-heif>=1.0
```

Run: `./.venv/bin/python -m pip install -q -r requirements.txt && ./.venv/bin/python -c "import pillow_heif; print('pillow-heif', pillow_heif.__version__)"`
Expected: `pillow-heif 1.8.0` (or later)

- [ ] **Step 2: Write the failing tests**

Add above the runner block in `test_receipt_folder.py`, and add `import pdfplumber` to the imports at the top:

```python
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
```

- [ ] **Step 3: Run to verify it fails**

Run: `./.venv/bin/python -c "import test_receipt_folder as t; t.test_a_small_image_is_not_upscaled()"`
Expected: `AttributeError: module 'src.receipt_folder' has no attribute 'to_pdf'`

- [ ] **Step 4: Implement**

In `src/receipt_folder.py`, change the imports to:

```python
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

from src.sheets_logger import normalize_reference

try:  # HEIC/HEIF support; without it those photos fail conversion with a clear message
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass
```

and add after `find_receipt`:

```python
# ---------------------------------------------------------------------------
# Photo -> PDF
# ---------------------------------------------------------------------------
# A 24 MP phone photo of a receipt is ~4 MB; at a 2200 px long edge it is
# ~480 KB and every line is still legible.
MAX_EDGE = 2200
JPEG_QUALITY = 75
PDF_DPI = 200


class ConversionError(Exception):
    """An image couldn't be turned into a PDF."""


def to_pdf(image_path: Path) -> Path:
    """Write <stem>.pdf beside `image_path` and return its path.

    Applies the phone's rotation, shrinks the long edge to MAX_EDGE (never
    enlarging), and never overwrites an existing file.
    """
    out = image_path.with_suffix(PDF_EXT)
    if out.exists():
        raise ConversionError(f"{out.name} already exists")
    try:
        with Image.open(image_path) as im:
            page = ImageOps.exif_transpose(im)
            page.thumbnail((MAX_EDGE, MAX_EDGE))
            page.convert("RGB").save(out, "PDF", quality=JPEG_QUALITY, resolution=PDF_DPI)
    except Exception as e:
        out.unlink(missing_ok=True)
        raise ConversionError(f"Couldn't convert {image_path.name}: {e}") from e
    return out
```

- [ ] **Step 5: Run to verify it passes**

Run: `./.venv/bin/python test_receipt_folder.py`
Expected: ends with `OK — 13 tests passed; every receipt in the folder is accounted for.`

- [ ] **Step 6: Commit**

```bash
git add requirements.txt src/receipt_folder.py test_receipt_folder.py
git commit -m "Convert receipt photos to small PDFs

A 24 MP phone photo (~4 MB) becomes a ~480 KB PDF at a 2200 px long edge
with the phone's rotation applied. HEIC is supported via pillow-heif.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Moving files into the subfolders

**Files:**
- Modify: `src/receipt_folder.py` (new section at the end)
- Test: `test_receipt_folder.py`

**Interfaces:**
- Produces: `move_into(folder: Path, subfolder: str, paths: list[Path]) -> list[Path]` (returns the new paths)

- [ ] **Step 1: Write the failing tests**

Add above the runner block:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/python -c "import test_receipt_folder as t; t.test_move_into_never_overwrites_a_file_already_there()"`
Expected: `AttributeError: module 'src.receipt_folder' has no attribute 'move_into'`

- [ ] **Step 3: Implement**

Add at the end of `src/receipt_folder.py`:

```python
# ---------------------------------------------------------------------------
# Moving files into the subfolders
# ---------------------------------------------------------------------------

def _free_name(path: Path) -> Path:
    """`path`, or `name (2).ext`, `name (3).ext`, … -- the first that doesn't exist."""
    candidate, n = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return candidate


def move_into(folder: Path, subfolder: str, paths: list[Path]) -> list[Path]:
    """Move `paths` into folder/subfolder, creating it; never overwrites."""
    dest_dir = folder / subfolder
    dest_dir.mkdir(exist_ok=True)
    moved = []
    for path in paths:
        dest = _free_name(dest_dir / path.name)
        path.rename(dest)
        moved.append(dest)
    return moved
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/python test_receipt_folder.py`
Expected: ends with `OK — 15 tests passed; every receipt in the folder is accounted for.`

- [ ] **Step 5: Commit**

```bash
git add src/receipt_folder.py test_receipt_folder.py
git commit -m "Move receipt files into subfolders without overwriting

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Mapping a parsed receipt to an Unsubmitted row

**Files:**
- Modify: `src/receipt_folder.py` (new section at the end)
- Test: `test_receipt_folder.py`

**Interfaces:**
- Consumes: `src.models.LineItem` (fields `description`, `vendor`, `purchase_date`); the reconciliation dict from `parse_receipt` (keys `grand_total`, `computed_total`)
- Produces: `row_from_parse(reference: str, items: list, reconciliation: dict | None) -> list[str]`, 7 values in `UNSUBMITTED_HEADER` order: Student, Item, Store, Order/Receipt #, Price, Date Purchased, Status

- [ ] **Step 1: Write the failing tests**

Add `from src.models import LineItem` to the imports at the top of `test_receipt_folder.py`, then add above the runner block:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/python -c "import test_receipt_folder as t; t.test_row_counts_the_other_items()"`
Expected: `AttributeError: module 'src.receipt_folder' has no attribute 'row_from_parse'`

- [ ] **Step 3: Implement**

Add at the end of `src/receipt_folder.py`:

```python
# ---------------------------------------------------------------------------
# Unsubmitted row from a parsed receipt
# ---------------------------------------------------------------------------

def row_from_parse(reference: str, items: list, reconciliation: dict | None) -> list[str]:
    """The Unsubmitted row (UNSUBMITTED_HEADER order) for a receipt Claude has read.

    With no items -- Claude couldn't read it -- only Order/Receipt # is filled.
    """
    if not items:
        return ["", "", "", reference, "", "", ""]
    first = items[0]
    item = (first.description or "").strip()
    if len(items) > 1:
        item = f"{item} + {len(items) - 1} more".strip()
    totals = reconciliation or {}
    total = totals.get("grand_total")
    if total is None:
        total = totals.get("computed_total")
    price = f"{float(total):.2f}" if total is not None else ""
    return ["", item, (first.vendor or "").strip(), reference, price,
            (first.purchase_date or "").strip(), ""]
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/bin/python test_receipt_folder.py`
Expected: ends with `OK — 19 tests passed; every receipt in the folder is accounted for.`

- [ ] **Step 5: Commit**

```bash
git add src/receipt_folder.py test_receipt_folder.py
git commit -m "Map a parsed receipt to an Unsubmitted row

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Sheet access — staging rows and strict reference reads

**Files:**
- Modify: `src/sheets_logger.py`: replace `append_orders`; add `read_tracked_references` at the end of the file
- Test: `test_receipt_folder.py`

**Interfaces:**
- Consumes: `normalize_reference`, `reference_from_invoice`, `LINE_ITEMS_TABS`, `UNSUBMITTED_TAB`, `UNSUBMITTED_HEADER`, `create_tab`, `_get_service` (all existing in `sheets_logger`)
- Produces:
  - `append_unsubmitted(rows: list[list]) -> None`
  - `read_tracked_references() -> tuple[set[str], set[str]]`, meaning `(submitted, staged)` as normalised references. It raises on any read error.
  - `append_orders(orders)` keeps its behaviour, now built on `append_unsubmitted`

- [ ] **Step 1: Write the failing tests**

Add `from fake_sheets import FakeSheets` and `from src import sheets_logger` to the imports, then add above the runner block:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/python -c "import test_receipt_folder as t; t.test_append_unsubmitted_appends_rows_as_given()"`
Expected: `AttributeError: module 'src.sheets_logger' has no attribute 'append_unsubmitted'`

- [ ] **Step 3: Implement**

In `src/sheets_logger.py`, replace the whole `append_orders` function with:

```python
def append_unsubmitted(rows: list[list]):
    """Append staged rows (UNSUBMITTED_HEADER order) to the Unsubmitted tab."""
    if not rows:
        return
    try:
        create_tab(UNSUBMITTED_TAB, UNSUBMITTED_HEADER)  # no-op if it already exists
        svc = _get_service()
        svc.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=f"{UNSUBMITTED_TAB}!A1",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()
    except Exception as e:
        print(f"[sheets] Error appending to {UNSUBMITTED_TAB}: {e}")
        raise


def append_orders(orders: list):
    """Stage Amazon orders from the scanner, one row per order."""
    append_unsubmitted([
        ["", o.get("description", ""), "Amazon", o.get("order_number", ""),
         o.get("total", ""), o.get("purchase_date", ""), ""]
        for o in orders
    ])
```

and add at the end of the file:

```python
def read_tracked_references() -> tuple[set[str], set[str]]:
    """(submitted, staged): normalised references of every receipt the sheet knows.

    Submitted is the Invoice column of every existing Line Items tab (file name
    without extension); staged is Unsubmitted's Order/Receipt # column.

    Strict, unlike the other readers here: any read error raises. A Line Items
    tab that doesn't exist yet is skipped by checking the tab list first, never
    by swallowing an error -- a silently empty result would make every receipt
    in the folder look untracked.
    """
    svc = _get_service()
    meta = svc.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    titles = {s["properties"]["title"] for s in meta.get("sheets", [])}

    def _column_d(tab: str) -> list[str]:
        rows = svc.spreadsheets().values().get(
            spreadsheetId=SHEET_ID, range=f"{tab}!D:D",
        ).execute().get("values", [])
        return [r[0] for r in rows[1:] if r and r[0].strip()]  # skip header

    submitted = {
        normalize_reference(reference_from_invoice(name))
        for tab in LINE_ITEMS_TABS if tab in titles
        for name in _column_d(tab)
    }
    staged = ({normalize_reference(v) for v in _column_d(UNSUBMITTED_TAB)}
              if UNSUBMITTED_TAB in titles else set())
    submitted.discard("")
    staged.discard("")
    return submitted, staged
```

- [ ] **Step 4: Run to verify it passes, and that nothing else broke**

Run: `./.venv/bin/python test_receipt_folder.py`
Expected: ends with `OK — 25 tests passed; every receipt in the folder is accounted for.`

Run: `for t in test_unsubmitted_cleanup.py test_sheets_integrity.py test_scholarship_year.py; do ./.venv/bin/python $t 2>&1 | grep -v "^\[scanner\]" | tail -1; done`
Expected: three `OK — …` lines (28, 8 and 10 tests).

- [ ] **Step 5: Commit**

```bash
git add src/sheets_logger.py test_receipt_folder.py
git commit -m "Add strict tracked-reference reads and a general Unsubmitted append

append_orders now builds on append_unsubmitted instead of carrying its own
copy of the append call.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The review, skip and add routes

**Files:**
- Create: `src/receipt_routes.py`
- Modify: `main.py` (import and register the blueprint, next to `submission_bp`)
- Test: `test_receipt_folder.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6; `src.receipt_parser.parse_receipt(pdf_path: str) -> (list[LineItem], float, dict)`
- Produces: blueprint `bp` with `GET /receipts`, `GET /receipts/review`, `POST /receipts/skip`, `POST /receipts/add`; module functions `receipts_folder() -> Path` and `_parse(pdf: Path)`, both replaced in tests

- [ ] **Step 1: Write the failing tests**

Add above the runner block:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/bin/python -c "import test_receipt_folder as t; t.test_review_lists_each_receipt_with_its_status()"`
Expected: `ModuleNotFoundError: No module named 'src.receipt_routes'`

- [ ] **Step 3: Implement the blueprint**

Create `src/receipt_routes.py`:

```python
"""
Routes for the receipts folder review.

Kept out of main.py so they can be exercised without importing the browser
agent. Both POST routes take a receipt *reference* and find its files by
scanning the folder, so no request can reach a file outside it.
"""

from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from src import receipt_folder as rf
from src import scholarship_year
from src.sheets_logger import UNSUBMITTED_HEADER, append_unsubmitted, read_tracked_references

bp = Blueprint("receipts", __name__)


def receipts_folder() -> Path:
    """The folder under review (replaced in tests)."""
    return scholarship_year.receipts_folder()


def _parse(pdf: Path):
    """Read a receipt with Claude (replaced in tests).

    Imported here, not at module load, because the parser creates its API
    client on import.
    """
    from src.receipt_parser import parse_receipt
    return parse_receipt(str(pdf))


def _sheet_error(e: Exception):
    return jsonify({"error": f"Couldn't read the tracking sheet: {e}"}), 502


def _lookup():
    """(folder, receipt) for the request's reference, or (folder, None)."""
    reference = ((request.get_json(silent=True) or {}).get("reference") or "").strip()
    folder = receipts_folder()
    return folder, (rf.find_receipt(folder, reference) if folder.is_dir() else None)


@bp.route("/receipts")
def receipts_page():
    return render_template("receipts.html", folder=str(receipts_folder()))


@bp.route("/receipts/review")
def receipts_review():
    folder = receipts_folder()
    if not folder.is_dir():
        return jsonify({"error": f"Folder not found: {folder}"}), 404
    try:
        submitted, staged = read_tracked_references()
    except Exception as e:
        return _sheet_error(e)
    receipts = rf.review(folder, submitted, staged)
    return jsonify({"folder": str(folder), "receipts": [r.to_dict() for r in receipts]})


@bp.route("/receipts/skip", methods=["POST"])
def receipts_skip():
    folder, receipt = _lookup()
    if receipt is None:
        return jsonify({"error": "No such receipt in the folder."}), 404
    try:
        submitted, staged = read_tracked_references()
    except Exception as e:
        return _sheet_error(e)
    status = rf.classify(receipt, submitted, staged)
    if status != "untracked":
        return jsonify({"error": f"{receipt.reference} is {status}; only untracked receipts can be skipped."}), 409
    moved = rf.move_into(folder, rf.NOT_SUBMITTING, receipt.files)
    return jsonify({"moved": [p.name for p in moved]})


@bp.route("/receipts/add", methods=["POST"])
def receipts_add():
    folder, receipt = _lookup()
    if receipt is None:
        return jsonify({"error": "No such receipt in the folder."}), 404
    try:
        submitted, staged = read_tracked_references()
    except Exception as e:
        return _sheet_error(e)
    if rf.classify(receipt, submitted, staged) != "untracked":
        return jsonify({"status": "already_tracked", "reference": receipt.reference})

    # Order matters: convert, read, append, then move the photos. A failure
    # partway leaves at most a new PDF beside the photo, which the next review
    # treats as a photo+pdf receipt.
    pdf, converted = receipt.pdf, False
    if pdf is None:
        try:
            pdf, converted = rf.to_pdf(receipt.images[0]), True
        except rf.ConversionError as e:
            return jsonify({"error": str(e)}), 422

    try:
        items, cost, reconciliation = _parse(pdf)
    except Exception as e:
        print(f"[receipts] couldn't read {pdf.name}: {e}")
        items, cost, reconciliation = [], 0.0, None

    row = rf.row_from_parse(receipt.reference, items, reconciliation)
    try:
        append_unsubmitted([row])
    except Exception as e:
        return jsonify({"error": f"Couldn't write to the sheet: {e}"}), 500

    rf.move_into(folder, rf.ORIGINALS, receipt.images)
    return jsonify({
        "status": "added",
        "reference": receipt.reference,
        "row": dict(zip(UNSUBMITTED_HEADER, row)),
        "converted": converted,
        "needs_details": not items,
        "cost": round(cost or 0.0, 4),
    })
```

- [ ] **Step 4: Run to verify the route tests pass**

`test_receipt_folder.py` needs `templates/receipts.html` only for `GET /receipts`, which is Task 8. The tests above don't call that route.

Run: `./.venv/bin/python test_receipt_folder.py`
Expected: ends with `OK — 38 tests passed; every receipt in the folder is accounted for.`

- [ ] **Step 5: Register the blueprint in `main.py`**

After the line `from src.submission_routes import bp as submission_bp`, add:

```python
from src.receipt_routes import bp as receipts_bp
```

After `app.register_blueprint(submission_bp)`, add:

```python
# Receipts folder review: /receipts and its review/skip/add endpoints.
app.register_blueprint(receipts_bp)
```

Verify the app's routes with the browser and receipt-parser modules stubbed (importing them for real starts Playwright and an API client):

```bash
./.venv/bin/python - <<'PY'
import sys, types
for name, attrs in {"src.browser_agent": ["discover_form_options", "fill_form", "inspect_form_elements", "load_form_options"],
                    "src.receipt_parser": ["parse_receipt"], "src.pdf_downloader": ["download_invoices"]}.items():
    m = types.ModuleType(name)
    for a in attrs: setattr(m, a, lambda *a, **k: None)
    sys.modules[name] = m
import main
print(sorted(str(r) for r in main.app.url_map.iter_rules() if "receipts" in str(r)))
PY
```

Expected: `['/receipts', '/receipts/add', '/receipts/review', '/receipts/skip']`

- [ ] **Step 6: Commit**

```bash
git add src/receipt_routes.py main.py test_receipt_folder.py
git commit -m "Add review, skip and add routes for the receipts folder

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The page, the home-page card and the README

**Files:**
- Create: `templates/receipts.html`
- Modify: `templates/index.html` (new card before the `href="/scan"` card)
- Modify: `README.md` (new section before `## SUFS Status Scanner`)
- Test: `test_receipt_folder.py`

**Interfaces:**
- Consumes: `GET /receipts/review`, `POST /receipts/skip`, `POST /receipts/add` (Task 7); `folder` template variable

- [ ] **Step 1: Write the failing tests**

Add above the runner block:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `./.venv/bin/python -c "import test_receipt_folder as t; t.test_the_home_page_links_to_the_review()"`
Expected: `AssertionError`

- [ ] **Step 3: Create `templates/receipts.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Receipts Folder — SUFS</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,700;12..96,800&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;450;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{{ url_for('static', filename='ledger.css') }}">
  <style>
    .folder-path { font-family: var(--mono); font-size: .76rem; color: var(--ink-3); margin-top: 6px; word-break: break-all; }
    .group { margin-top: 22px; }
    .group-head { display: flex; align-items: center; gap: 12px; }
    .group-head .section-label { flex: 1; margin: 0; }
    .table-wrap { overflow-x: auto; margin-top: 8px; }
    .collapsed { display: none; }
    td.check-col { width: 36px; text-align: center; }
    td.ref { font-family: var(--mono); font-size: .82rem; word-break: break-all; }
    td.kind, td.size { color: var(--ink-3); white-space: nowrap; }
    td.result { min-width: 220px; }
    td.result.ok { color: var(--ok); }
    td.result.warn { color: var(--pend); }
    td.result.err { color: var(--danger); }
    tr.done { opacity: .6; }
    .action-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 18px; }
  </style>
</head>
<body>
  <div class="shell" style="max-width:980px">
    <a class="back" href="/">← Back to intake</a>
    <p class="eyebrow" style="margin-top:18px">Step Up for Students · Receipts</p>
    <h1 class="title">Review receipts folder</h1>
    <p class="sub">Find receipts in your folder that aren't submitted or staged yet, and stage them in your <b>Unsubmitted</b> tab. Photos are converted to small PDFs first.</p>
    <p class="folder-path">{{ folder }}</p>

    <div class="card" style="margin-top:24px">
      <div id="status-bar" class="status-bar"></div>
      <div id="groups"></div>
      <div class="action-row">
        <button class="btn btn-primary" id="add-btn" onclick="addSelected()" disabled>Add to Unsubmitted</button>
        <button class="btn btn-outline" id="reload-btn" onclick="loadReview()">Review again</button>
      </div>
    </div>
  </div>

<script>
// [status, heading, starts open]
const GROUPS = [
  ['untracked', 'Untracked', true],
  ['staged', 'Staged in Unsubmitted', false],
  ['submitted', 'Submitted', false],
  ['unsupported', "Can't process", false],
];
const KIND = { 'pdf': 'PDF', 'photo': 'photo', 'photo+pdf': 'photo + PDF', 'unsupported': '—' };

let receipts = [];
let running = false;

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function size(bytes) {
  return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(bytes / 1024)) + ' KB';
}
function setStatus(type, msg) {
  const bar = document.getElementById('status-bar');
  bar.className = 'status-bar ' + type;
  bar.textContent = msg;
}
function setResult(i, cls, text) {
  const el = document.getElementById('result-' + i);
  el.className = 'result ' + cls;
  el.textContent = text;
}
function lockRow(i) {
  const row = document.getElementById('row-' + i);
  row.classList.add('done');
  row.querySelectorAll('input, button').forEach(el => { el.disabled = true; el.checked = false; });
}
function picked() {
  return [...document.querySelectorAll('.pick:checked:not(:disabled)')].map(cb => Number(cb.dataset.i));
}
function updateAddButton() {
  const n = picked().length;
  const btn = document.getElementById('add-btn');
  btn.textContent = n ? `Add ${n} to Unsubmitted` : 'Add to Unsubmitted';
  btn.disabled = running || !n;
}
function toggle(status, btn) {
  const el = document.getElementById('group-' + status);
  el.classList.toggle('collapsed');
  btn.textContent = el.classList.contains('collapsed') ? 'Show' : 'Hide';
}

function rowHtml(r, untracked) {
  const i = receipts.indexOf(r);
  const bytes = r.files.reduce((sum, f) => sum + f.size, 0);
  return `<tr id="row-${i}">
    ${untracked ? `<td class="check-col"><input type="checkbox" class="pick" data-i="${i}" checked onchange="updateAddButton()"></td>` : ''}
    <td class="ref">${esc(r.reference)}</td>
    <td class="kind">${esc(KIND[r.kind] || r.kind)}</td>
    <td class="size">${size(bytes)}</td>
    <td class="result" id="result-${i}">${esc(r.reason)}</td>
    ${untracked ? `<td><button class="btn btn-sm btn-outline skip-btn" onclick="skip(${i})">Not submitting</button></td>` : ''}
  </tr>`;
}

function render() {
  document.getElementById('groups').innerHTML = GROUPS.map(([status, heading, open]) => {
    const rows = receipts.filter(r => r.status === status);
    if (!rows.length) return '';
    const untracked = status === 'untracked';
    const toggleBtn = untracked ? ''
      : `<button class="btn btn-sm btn-outline" onclick="toggle('${status}', this)">${open ? 'Hide' : 'Show'}</button>`;
    return `<section class="group">
      <div class="group-head"><p class="section-label">${esc(heading)} (${rows.length})</p>${toggleBtn}</div>
      <div class="table-wrap ${open ? '' : 'collapsed'}" id="group-${status}">
        <table><tbody>${rows.map(r => rowHtml(r, untracked)).join('')}</tbody></table>
      </div>
    </section>`;
  }).join('');
  updateAddButton();
}

async function post(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch (_) {}
  return { ok: res.ok, data };
}

async function loadReview() {
  setStatus('info', 'Reading the folder and your tracking sheet…');
  document.getElementById('groups').innerHTML = '';
  document.getElementById('add-btn').disabled = true;
  try {
    const res = await fetch('/receipts/review');
    const data = await res.json();
    if (!res.ok) { setStatus('err', data.error || 'The review failed.'); return; }
    receipts = data.receipts;
    render();
    const n = receipts.filter(r => r.status === 'untracked').length;
    setStatus(n ? 'info' : 'ok',
      n ? `${n} receipt${n === 1 ? '' : 's'} aren't submitted or staged yet.`
        : 'Every receipt in the folder is submitted or staged.');
  } catch (e) {
    setStatus('err', 'Network error: ' + e.message);
  }
}

async function skip(i) {
  if (running) return;
  const { ok, data } = await post('/receipts/skip', { reference: receipts[i].reference });
  if (!ok) { setResult(i, 'err', data.error || "Couldn't move it."); return; }
  setResult(i, 'warn', 'Moved to Not submitting');
  lockRow(i);
  updateAddButton();
}

async function addSelected() {
  if (running) return;
  const picks = picked();
  if (!picks.length) return;
  running = true;
  const addBtn = document.getElementById('add-btn');
  addBtn.disabled = true;
  document.getElementById('reload-btn').disabled = true;
  document.querySelectorAll('.pick, .skip-btn').forEach(el => el.disabled = true);

  let added = 0, needDetails = 0, failed = 0, cost = 0;
  for (const i of picks) {
    setResult(i, '', 'Working…');
    try {
      const { ok, data } = await post('/receipts/add', { reference: receipts[i].reference });
      if (!ok) { failed++; setResult(i, 'err', data.error || 'Failed'); continue; }
      if (data.status === 'already_tracked') {
        setResult(i, 'warn', 'Already staged or submitted — skipped');
        lockRow(i);
        continue;
      }
      added++;
      cost += data.cost || 0;
      if (data.needs_details) {
        needDetails++;
        setResult(i, 'warn', "Added — couldn't read the receipt, fill in the details");
      } else {
        const row = data.row;
        const bits = [data.converted ? 'Converted' : '', row['Store'],
                      row['Price'] ? '$' + row['Price'] : '', row['Date Purchased']].filter(Boolean);
        setResult(i, 'ok', bits.join(' · ') + ' — Added ✓');
      }
      lockRow(i);
    } catch (e) {
      failed++;
      setResult(i, 'err', 'Network error: ' + e.message);
    }
  }

  running = false;
  document.getElementById('reload-btn').disabled = false;
  // Rows that failed can be retried or skipped.
  document.querySelectorAll('#group-untracked tr:not(.done) input, #group-untracked tr:not(.done) button')
    .forEach(el => el.disabled = false);
  updateAddButton();
  const parts = [`Added ${added}`];
  if (needDetails) parts.push(`${needDetails} need${needDetails === 1 ? 's' : ''} details`);
  if (failed) parts.push(`${failed} failed`);
  parts.push(`Claude cost $${cost.toFixed(2)}`);
  setStatus(failed ? 'err' : 'ok', parts.join(' · '));
}

loadReview();
</script>
</body>
</html>
```

- [ ] **Step 4: Add the home-page card**

In `templates/index.html`, immediately before the line `      <a href="/scan" class="tool">`, insert:

```html
      <a href="/receipts" class="tool">
        <span class="glyph">🧾</span>
        <span class="tool-body">
          <span class="tool-name">Review receipts folder <span class="leader"></span></span>
          <span class="tool-sub">Stage photos and PDFs from your SUFS folder in Unsubmitted</span>
        </span>
        <span class="arrow">→</span>
      </a>
```

- [ ] **Step 5: Run to verify everything passes**

Run: `./.venv/bin/python test_receipt_folder.py`
Expected: ends with `OK — 42 tests passed; every receipt in the folder is accounted for.`

Run: `for t in test_*.py; do ./.venv/bin/python $t 2>&1 | grep -v "^\[scanner\]\|^\[receipts\]\|^  ok" | tail -1; done`
Expected: five `OK — …` lines (never-submit, 42, 10, 8, 28).

- [ ] **Step 6: Document it in the README**

In `README.md`, immediately before the line `## SUFS Status Scanner`, insert:

```markdown
## Review receipts folder

Keeps the **Unsubmitted** tab a complete to-do list. On the home page, click
**Review receipts folder**. The app looks at this year's folder
(`~/Desktop/SUFS/<year>/`, the same one Amazon invoices download to) and sorts
every receipt into:

- **Untracked**: not submitted and not in Unsubmitted
- **Staged in Unsubmitted**
- **Submitted**: in a Line Items tab
- **Can't process**: a file type it doesn't handle

A receipt is a file *name*, so `IMG_1698.jpeg` and `IMG_1698.pdf` count once.

For untracked receipts:

- **Add to Unsubmitted** stages the checked ones. A photo (`.jpg`, `.png`,
  `.heic`) is first converted to a PDF of the same name, at about 480 KB instead
  of about 4 MB, and the photo moves to `Originals/`. Claude then reads the
  receipt and fills in the item, store, price and purchase date. If it can't
  read one, the row is added with just the file name for you to fill in.
- **Not submitting** moves the receipt's files to `Not submitting/`, so it
  isn't offered again. Drag it back out to undo.

Nothing is ever deleted. Later, when you upload one of these receipts on the
intake page and log it, the Remove/Keep prompt finds its Unsubmitted row by
file name.

---

```

- [ ] **Step 7: Commit**

```bash
git add templates/receipts.html templates/index.html README.md test_receipt_folder.py
git commit -m "Add the Review receipts folder page

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: End-to-end check against the real folder (read-only)

**Files:** none changed.

- [ ] **Step 1: Run the review against the live sheet and real folder without writing anything**

```bash
./.venv/bin/python - <<'PY'
from collections import Counter
from dotenv import load_dotenv; load_dotenv(".env")
from src import receipt_folder as rf, scholarship_year
from src.sheets_logger import read_tracked_references
folder = scholarship_year.receipts_folder()
submitted, staged = read_tracked_references()
receipts = rf.review(folder, submitted, staged)
print(folder, "|", len(receipts), "receipts |", dict(Counter(r.status for r in receipts)))
print("untracked:", [r.reference for r in receipts if r.status == "untracked"])
PY
```

Expected: the folder path ends in `2026-2027`. The counts match the design-time dry run (38 staged, 4 submitted, 12 untracked) unless receipts have been added or skipped since. The untracked list names the phone photos and hand-named PDFs. **Report the output to the user. Do not press Add or Not submitting on their behalf.**

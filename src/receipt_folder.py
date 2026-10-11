"""
The receipts folder review: which receipts in the scholarship-year folder are
submitted, staged in Unsubmitted, or not tracked at all, plus the file work
needed to stage the untracked ones.

Folder logic only -- no sheet or Claude calls -- so all of it is testable
against a temporary folder. A receipt is a *name*: every top-level file that
shares a normalised name is one receipt, so IMG_1698.jpeg and IMG_1698.pdf
count once.
"""

import io
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

from src.sheets_logger import normalize_reference

try:  # HEIC/HEIF support; without it those photos fail conversion with a clear message
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

PDF_EXT = ".pdf"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}

# Subfolders of the year folder. The review reads only the top level, so
# anything moved into these is never offered again.
ORIGINALS = "Originals"
NOT_SUBMITTING = "Not submitting"
SUBMITTED = "Submitted"


def _supported(path: Path) -> bool:
    ext = path.suffix.lower()
    return ext == PDF_EXT or ext in IMAGE_EXTS


def is_real_pdf(path: Path) -> bool:
    """True if the file's contents are a PDF, whatever its name says.

    A photo renamed to .pdf isn't one: Claude's API rejects it ("The PDF
    specified was not valid") and SUFS needs a real PDF too.
    """
    try:
        with open(path, "rb") as f:
            return b"%PDF-" in f.read(1024)
    except OSError:
        return False


@dataclass
class Receipt:
    reference: str               # file name without extension, as on disk
    files: list[Path] = field(default_factory=list)
    status: str = "untracked"    # submitted | staged | untracked | unsupported
    reason: str = ""
    # Which .pdf files really are PDFs, checked once when the receipt is built, so
    # the receipt describes the folder as it was reviewed and isn't re-read on
    # every access.
    real_pdfs: set[Path] = field(default_factory=set)

    def __post_init__(self):
        if not self.real_pdfs:
            self.real_pdfs = {f for f in self.files if f.suffix.lower() == PDF_EXT and is_real_pdf(f)}

    @property
    def pdf(self) -> Path | None:
        """The receipt's PDF, judged by its contents rather than its name."""
        return next((f for f in self.files if f in self.real_pdfs), None)

    @property
    def disguised(self) -> list[Path]:
        """Files named .pdf whose contents aren't a PDF -- usually a renamed photo."""
        return [f for f in self.files if f.suffix.lower() == PDF_EXT and f not in self.real_pdfs]

    @property
    def images(self) -> list[Path]:
        """The receipt's photos, including any saved under a .pdf name."""
        return sorted([f for f in self.files if f.suffix.lower() in IMAGE_EXTS] + self.disguised)

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


def _pdf_bytes_from_image(source) -> bytes:
    """A photo (path or file object) as PDF bytes: the phone's rotation applied,
    the long edge shrunk to MAX_EDGE (never enlarged)."""
    with Image.open(source) as im:
        page = ImageOps.exif_transpose(im)
        page.thumbnail((MAX_EDGE, MAX_EDGE))
        buf = io.BytesIO()
        page.convert("RGB").save(buf, "PDF", quality=JPEG_QUALITY, resolution=PDF_DPI)
        return buf.getvalue()


def to_pdf(image_path: Path, out: Path | None = None) -> Path:
    """Write the photo as a PDF (default <stem>.pdf beside it) and return its path.

    Never overwrites an existing file.
    """
    out = out or image_path.with_suffix(PDF_EXT)
    if out.exists():
        raise ConversionError(f"{out.name} already exists")
    try:
        data = _pdf_bytes_from_image(image_path)
    except Exception as e:
        raise ConversionError(f"Couldn't convert {image_path.name}: {e}") from e
    out.write_bytes(data)
    return out


def ensure_pdf_bytes(data: bytes) -> tuple[bytes, bool]:
    """(PDF bytes, whether they were converted) for an uploaded receipt.

    A real PDF passes through untouched. A photo -- often one renamed to .pdf --
    is converted the same way the folder review converts photos.
    """
    if b"%PDF-" in data[:1024]:
        return data, False
    try:
        return _pdf_bytes_from_image(io.BytesIO(data)), True
    except Exception as e:
        raise ConversionError(f"This file isn't a PDF, and it isn't a photo the app can read ({e}).") from e


_PHOTO_EXT = {"JPEG": ".jpg", "PNG": ".png", "HEIF": ".heic"}


def repair_disguised_pdf(folder: Path, receipt: Receipt) -> bool:
    """Turn a photo saved under a .pdf name into a real PDF at the same path.

    The photo's bytes are never lost: if an identical copy already exists (beside
    it or in Originals/), the renamed file is simply replaced; otherwise it is
    first moved into Originals/ under its real extension. Returns True if a file
    was repaired. Raises ConversionError, changing nothing, if the file is
    neither a PDF nor a photo the app can read.
    """
    if not receipt.disguised:
        return False
    fake = receipt.disguised[0]
    try:
        with Image.open(fake) as im:
            fmt = im.format
    except Exception as e:
        raise ConversionError(f"{fake.name} isn't a PDF, and it isn't a photo the app can read ({e}).") from e

    data = fake.read_bytes()
    originals = folder / ORIGINALS
    candidates = [f for f in receipt.files if f != fake]
    if originals.is_dir():
        candidates += sorted(p for p in originals.iterdir() if p.stem == fake.stem)
    twin = next((c for c in candidates if c.is_file() and c.stat().st_size == len(data)
                 and c.read_bytes() == data), None)

    if twin is not None:
        try:
            fake.write_bytes(_pdf_bytes_from_image(twin))    # the photo survives as its twin
        except Exception as e:
            fake.write_bytes(data)
            raise ConversionError(f"Couldn't convert {fake.name}: {e}") from e
        return True

    originals.mkdir(exist_ok=True)
    kept = _free_name(originals / f"{fake.stem}{_PHOTO_EXT.get(fmt, '.img')}")
    fake.rename(kept)
    try:
        fake.write_bytes(_pdf_bytes_from_image(kept))
    except Exception as e:
        fake.unlink(missing_ok=True)
        kept.rename(fake)                                     # put the photo back as it was
        raise ConversionError(f"Couldn't convert {fake.name}: {e}") from e
    return True


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


# ---------------------------------------------------------------------------
# Filing a finished receipt
# ---------------------------------------------------------------------------

def file_as_submitted(folder: Path, reference: str) -> list[Path]:
    """Move a finished receipt's top-level files into Submitted/.

    Returns the new paths; [] when the folder or the receipt isn't there (e.g.
    it was uploaded from Downloads). Photos already in Originals/ stay put.
    """
    if not folder.is_dir():
        return []
    receipt = find_receipt(folder, reference)
    return move_into(folder, SUBMITTED, receipt.files) if receipt else []


def split_submitted(folder: Path, submitted_refs: set[str],
                    staged_refs: set[str]) -> tuple[list[Receipt], list[Receipt]]:
    """(finished, waiting) among the submitted receipts in `folder`.

    Finished receipts are no longer in Unsubmitted and belong in Submitted/.
    Waiting ones are still in Unsubmitted: submitted once per child, with more
    children to go, however many Line Items rows they already have.
    """
    submitted = [r for r in review(folder, submitted_refs, set()) if r.status == "submitted"]
    waiting = [r for r in submitted if normalize_reference(r.reference) in staged_refs]
    return [r for r in submitted if r not in waiting], waiting


def finished_receipts(folder: Path, submitted_refs: set[str], staged_refs: set[str]) -> list[Receipt]:
    """Submitted receipts no longer in Unsubmitted: ready to file in Submitted/."""
    return split_submitted(folder, submitted_refs, staged_refs)[0]

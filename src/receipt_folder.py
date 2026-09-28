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

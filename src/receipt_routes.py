"""
Routes for the receipts folder review.

Kept out of main.py so they can be exercised without importing the browser
agent. Both POST routes take a receipt *reference* and find its files by
scanning the folder, so no request can reach a file outside it.
"""

import functools
import threading
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from src import receipt_folder as rf
from src import scholarship_year
from src.sheets_logger import UNSUBMITTED_HEADER, append_unsubmitted, read_tracked_references

bp = Blueprint("receipts", __name__)

# Skip and add each read the sheet, then move files or append a row. The app
# serves requests on threads, so without this a Not submitting clicked just
# before Add could see the receipt untracked in both requests: the skip moves
# the files away and the add still stages a row for it.
_folder_lock = threading.Lock()


def _one_at_a_time(view):
    @functools.wraps(view)
    def locked(*args, **kwargs):
        with _folder_lock:
            return view(*args, **kwargs)
    return locked


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
@_one_at_a_time
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
@_one_at_a_time
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

"""
Routes for logging a submission and tidying the Unsubmitted staging tab.

Kept out of main.py so they can be exercised without importing the browser
agent or the receipt parser, neither of which this flow touches.

The cleanup is always user-driven: logging a submission never removes an
Unsubmitted row by itself, because one order is often reimbursed separately
for each child and only the user knows when the last one is done.

A finished receipt's file is moved from the year folder into Submitted/:
right after logging when the receipt isn't staged (nothing says more children
are coming), or when "Remove from Unsubmitted" is chosen. "Keep" leaves it in
place for the next child's upload.
"""

from pathlib import Path

from flask import Blueprint, jsonify, request, session

from src import receipt_folder, scholarship_year, students
from src.sheets_logger import (
    AlreadyLoggedError,
    delete_unsubmitted_row,
    find_unsubmitted_row,
    log_submission_to_testing,
    mark_unsubmitted_partial,
    reference_from_invoice,
)

bp = Blueprint("submission", __name__)


def receipts_folder() -> Path:
    """The year folder receipts are filed from (replaced in tests)."""
    return scholarship_year.receipts_folder()


def students_file() -> Path:
    """The saved Students list (replaced in tests)."""
    return students.STUDENTS_FILE


def _student_name(typed: str) -> str:
    """A saved child's name in its saved spelling, so "zion" and "ZIon" log as
    one child; a name that isn't saved is kept as typed."""
    return students.canonical_name(typed, students.load_students(students_file()))


def _file_receipt(reference: str) -> dict:
    """Move a finished receipt into Submitted/.

    Never raises: it runs after the sheet write has succeeded, and a failed
    move must not turn that success into an error.
    """
    try:
        moved = receipt_folder.file_as_submitted(receipts_folder(), reference)
    except Exception as e:
        print(f"[submitted] couldn't file {reference}: {e}")
        return {"moved": [], "error": f"Couldn't move the receipt to Submitted: {e}"}
    return {"moved": [p.name for p in moved]}


@bp.route("/log-submission", methods=["POST"])
def log_submission():
    data = request.get_json() or {}
    student = data.get("student", "").strip()
    sufs_id = data.get("sufs_id", "").strip()
    items = [i for i in data.get("items", []) if i.get("include")]

    if not student or not sufs_id:
        return jsonify({"error": "Student name and SUFS ID are required."}), 400
    if not items:
        return jsonify({"error": "No selected items to log."}), 400
    student = _student_name(student)

    invoice_filename = session.get("invoice_filename", "")
    try:
        log_submission_to_testing(student, sufs_id, items, invoice_filename)
    except AlreadyLoggedError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # The rows are safely logged at this point. Looking up the staged order is a
    # convenience for the next prompt, so a failure here must not report the
    # submission as failed.
    reference = reference_from_invoice(invoice_filename)
    staged, lookup_failed = None, False
    try:
        staged = find_unsubmitted_row(reference)
    except Exception as e:
        lookup_failed = True
        print(f"[unsubmitted] lookup failed for {invoice_filename}: {e}")

    # A staged receipt waits for the Remove/Keep choice. So does one whose
    # staging couldn't be checked: more children may still be coming.
    if staged or lookup_failed:
        filed = {"moved": [], "deferred": True}
    else:
        filed = _file_receipt(reference)

    return jsonify({"success": True, "logged": len(items), "unsubmitted": staged, "filed": filed})


def _reference():
    """The Order/Receipt # from the request body, plus the body itself."""
    data = request.get_json() or {}
    return (data.get("order_number") or "").strip(), data


@bp.route("/unsubmitted/remove", methods=["POST"])
def unsubmitted_remove():
    reference, _ = _reference()
    if not reference:
        return jsonify({"error": "No order/receipt reference supplied."}), 400
    try:
        removed = delete_unsubmitted_row(reference)
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    # Remove means the receipt is finished, whether or not the row was still there.
    return jsonify({"removed": removed, "filed": _file_receipt(reference)})


@bp.route("/unsubmitted/mark", methods=["POST"])
def unsubmitted_mark():
    reference, data = _reference()
    if not reference:
        return jsonify({"error": "No order/receipt reference supplied."}), 400
    try:
        status = mark_unsubmitted_partial(
            reference,
            _student_name(data.get("student") or ""),
            (data.get("sufs_id") or "").strip(),
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": status})

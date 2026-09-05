"""
Routes for logging a submission and tidying the Unsubmitted staging tab.

Kept out of main.py so they can be exercised without importing the browser
agent or the receipt parser, neither of which this flow touches.

The cleanup is always user-driven: logging a submission never removes anything
by itself, because one Amazon order is often reimbursed separately for each
child and only the user knows when the last one is done.
"""

from flask import Blueprint, jsonify, request, session

from src.sheets_logger import (
    delete_unsubmitted_row,
    find_unsubmitted_row,
    log_submission_to_testing,
    mark_unsubmitted_partial,
    reference_from_invoice,
)

bp = Blueprint("submission", __name__)


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

    invoice_filename = session.get("invoice_filename", "")
    try:
        log_submission_to_testing(student, sufs_id, items, invoice_filename)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # The rows are safely logged at this point. Looking up the staged order is a
    # convenience for the next prompt, so a failure here must not report the
    # submission as failed.
    staged = None
    try:
        staged = find_unsubmitted_row(reference_from_invoice(invoice_filename))
    except Exception as e:
        print(f"[unsubmitted] lookup failed for {invoice_filename}: {e}")

    return jsonify({"success": True, "logged": len(items), "unsubmitted": staged})


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
    return jsonify({"removed": removed})


@bp.route("/unsubmitted/mark", methods=["POST"])
def unsubmitted_mark():
    reference, data = _reference()
    if not reference:
        return jsonify({"error": "No order/receipt reference supplied."}), 400
    try:
        status = mark_unsubmitted_partial(
            reference,
            (data.get("student") or "").strip(),
            (data.get("sufs_id") or "").strip(),
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"status": status})

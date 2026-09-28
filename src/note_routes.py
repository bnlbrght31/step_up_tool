"""
Routes for the Students settings page and the shared-receipt note.

Kept out of main.py so they can be tested without importing the browser agent.
The note is built for the receipt currently on the confirm page, which the
upload stored in the session.
"""

import io
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, session

from src import receipt_note, students
from src.sheets_logger import reference_from_invoice

bp = Blueprint("notes", __name__)


def settings_path() -> Path:
    """Where student IDs are saved (replaced in tests)."""
    return students.STUDENTS_FILE


def _uploaded_reference() -> str:
    """The receipt on the confirm page, as a reference; "" if nothing is uploaded."""
    return reference_from_invoice(session.get("invoice_filename", ""))


def _receipt_summary() -> dict:
    """Store, date and total of the uploaded receipt, for the note's header."""
    items = session.get("items") or []
    first = items[0] if items else {}
    totals = session.get("reconciliation") or {}
    total = totals.get("grand_total")
    if total is None:
        total = totals.get("computed_total")
    return {"store": first.get("vendor") or "", "date": first.get("purchase_date") or "", "total": total}


@bp.route("/students")
def students_page():
    return render_template("students.html", students=students.load_students(settings_path()))


@bp.route("/students", methods=["POST"])
def students_save():
    rows = (request.get_json(silent=True) or {}).get("students") or []
    try:
        saved = students.save_students(rows, settings_path())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"students": saved})


@bp.route("/note/prior")
def note_prior():
    reference = _uploaded_reference()
    if not reference:
        return jsonify({"reference": "", "submissions": [], "missing_ids": []})
    try:
        submissions = receipt_note.prior_submissions(reference)
    except Exception as e:
        return jsonify({"error": f"Couldn't check the tracking sheet for earlier submissions: {e}"}), 502
    saved = students.load_students(settings_path())
    missing = [s["student"] for s in submissions if not students.student_id_for(s["student"], saved)]
    return jsonify({
        "reference": reference,
        "submissions": [{
            "student": s["student"],
            "reimbursement_id": s["reimbursement_id"],
            "date_submitted": s["date_submitted"],
            "item_count": len(s["items"]),
            "total": s["total"],
        } for s in submissions],
        "missing_ids": list(dict.fromkeys(missing)),
    })


@bp.route("/note.pdf")
def note_pdf():
    reference = _uploaded_reference()
    submissions = receipt_note.prior_submissions(reference) if reference else []
    if not submissions:
        return jsonify({"error": "This receipt has no earlier submission to reference."}), 404
    data = receipt_note.build_note_pdf(reference, submissions, _receipt_summary(),
                                       students.load_students(settings_path()))
    return send_file(io.BytesIO(data), mimetype="application/pdf", as_attachment=True,
                     download_name=f"{reference} - earlier submissions.pdf")

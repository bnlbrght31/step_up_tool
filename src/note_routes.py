"""
Routes for the Students settings page and the shared-receipt note.

Kept out of main.py so they can be tested without importing the browser agent.
The note is built for the receipt currently on the confirm page, which the
upload stored in the session.
"""

import io
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, session

from src import receipt_history, receipt_note, students
from src.sheets_logger import reference_from_invoice

bp = Blueprint("notes", __name__)


def settings_path() -> Path:
    """Where student IDs are saved (replaced in tests)."""
    return students.STUDENTS_FILE


def current_year() -> str:
    """The scholarship year the Students page edits (replaced in tests)."""
    return students.current_year()


def history_file() -> Path:
    """Where receipt history is kept (replaced in tests)."""
    return receipt_history.HISTORY_FILE


@bp.route("/receipt-history/status")
def receipt_history_status():
    """For the confirm page: whether this receipt's saved reading was reused, and
    a label for each item already submitted for a child (keyed by item position)."""
    entry = receipt_history.saved_reading(session.get("invoice_sha256", ""), history_file())
    labels = receipt_history.item_labels(entry)
    return jsonify({"reused": bool(session.get("reused_reading")),
                    "labels": {str(i): label for i, label in labels.items()}})


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
    """The current scholarship year's IDs. SUFS issues new ones every year, so
    after the July rollover the page asks for any that aren't entered yet."""
    year = current_year()
    saved = students.load_students(settings_path())
    return render_template(
        "students.html",
        students=students.year_view(saved, year),
        year=year.replace("-", "–"),
        needing=students.needing_new_ids(saved, year),
    )


@bp.route("/students", methods=["POST"])
def students_save():
    rows = (request.get_json(silent=True) or {}).get("students") or []
    try:
        saved = students.save_students(rows, settings_path(), year=current_year())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"students": saved})


@bp.route("/students/names")
def students_names():
    """The saved children's names for the confirm page's buttons. Names only:
    student IDs stay off the page and appear only in the downloaded note."""
    return jsonify({"names": students.names(students.load_students(settings_path()))})


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
    missing = [s["student"] for s in submissions
               if not students.student_id_for(s["student"], saved, s["year"] or current_year())]
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

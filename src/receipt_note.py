"""
The shared-receipt note.

When one receipt is reimbursed separately for each child, the second and later
submissions need to show what was already claimed from it. This finds those
earlier submissions in the Line Items tabs and builds a one-page PDF naming
each one -- child, SUFS student ID, reimbursement ID and items -- to attach to
the new submission.
"""

import re
from datetime import date

from fpdf import FPDF

from src.sheets_logger import normalize_reference, read_testing_rows, reference_from_invoice
from src.students import current_year, student_id_for


def _money(value) -> float:
    try:
        return round(float(re.sub(r"[^0-9.\-]", "", str(value or ""))), 2)
    except ValueError:
        return 0.0


def prior_submissions(reference: str, rows: list[dict] | None = None) -> list[dict]:
    """Earlier logged submissions of this receipt, one per SUFS reimbursement.

    A row belongs to the receipt when its Invoice column (the file name the
    upload page stored) matches `reference` under the app's usual
    normalisation. Returned oldest tab first, each as
    {student, reimbursement_id, date_submitted, year, items: [{description, price}], total},
    where `year` is the scholarship year of the Line Items tab it was logged in.
    """
    wanted = normalize_reference(reference)
    if not wanted:
        return []
    if rows is None:
        rows = read_testing_rows()
    submissions: dict[str, dict] = {}
    for row in rows:
        if normalize_reference(reference_from_invoice(row.get("invoice", ""))) != wanted:
            continue
        reimbursement_id = (row.get("sufs_reimb_id") or "").strip().split("-")[0]
        sub = submissions.setdefault(reimbursement_id, {
            "student": (row.get("student") or "").strip(),
            "reimbursement_id": reimbursement_id,
            "date_submitted": (row.get("date_submitted") or "").strip(),
            "year": (row.get("tab") or "").split(" ")[0],   # "2026-2027 Line Items" -> "2026-2027"
            "items": [],
            "total": 0.0,
        })
        price = _money(row.get("price"))
        sub["items"].append({"description": (row.get("item") or "").strip(), "price": price})
        sub["total"] = round(sub["total"] + price, 2)
    return list(submissions.values())


# ---------------------------------------------------------------------------
# The PDF
# ---------------------------------------------------------------------------

# The PDF's built-in fonts cover Latin-1 only, and item descriptions come from
# Claude, so typographic punctuation is mapped to plain ASCII and anything else
# outside Latin-1 (emoji, say) is dropped rather than failing the whole note.
_PLAIN = {"—": "-", "–": "-", "‘": "'", "’": "'",
          "“": '"', "”": '"', "…": "...", " ": " "}


def _latin1(text) -> str:
    text = "".join(_PLAIN.get(c, c) for c in str(text or ""))
    return text.encode("latin-1", "ignore").decode("latin-1").strip()


def _fit(pdf: FPDF, text: str, width: float) -> str:
    """`text`, shortened with '...' until it fits `width` at the current font."""
    if pdf.get_string_width(text) <= width:
        return text
    while text and pdf.get_string_width(text + "...") > width:
        text = text[:-1]
    return text.rstrip() + "..."


def build_note_pdf(reference: str, submissions: list[dict], receipt: dict,
                   students: list[dict]) -> bytes:
    """The note as PDF bytes.

    `receipt` may carry store, date and total for the header; `students` is the
    saved Students list. Each child's SUFS student ID is the one for the year the
    earlier submission was made, since SUFS issues new IDs every year.
    """
    pdf = FPDF(format="Letter")
    pdf.set_margins(22, 22)
    pdf.set_auto_page_break(True, 22)
    pdf.add_page()

    def line(text, size=11, style="", height=6):
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, height, _latin1(text), new_x="LMARGIN", new_y="NEXT")

    def amount_row(label, amount, bold=False):
        pdf.set_font("Helvetica", "B" if bold else "", 11)
        indent, price_width = 8, 28
        pdf.cell(indent, 6)
        label_width = pdf.epw - indent - price_width
        pdf.cell(label_width, 6, _fit(pdf, _latin1(label), label_width - 2))
        pdf.cell(price_width, 6, f"${amount:.2f}", align="R", new_x="LMARGIN", new_y="NEXT")

    total = receipt.get("total")
    header = " · ".join(part for part in (
        receipt.get("store"), receipt.get("date"),
        f"receipt total ${float(total):.2f}" if total is not None else "",
    ) if part)
    line("Shared receipt" + (f" - {header}" if header else ""), size=14, style="B", height=8)
    line(f"Receipt file: {reference}", size=10)
    pdf.ln(4)
    line("This receipt includes items for more than one student. "
         "These items on it were already submitted:")

    for sub in submissions:
        pdf.ln(3)
        year = sub.get("year") or current_year()
        student_id = student_id_for(sub["student"], students, year) or "not on file"
        line(f"{sub['student']} - SUFS student ID {student_id}", style="B")
        line(f"Reimbursement {sub['reimbursement_id'] or '(ID not recorded)'}, "
             f"submitted {sub['date_submitted'] or '(date not recorded)'}")
        for item in sub["items"]:
            amount_row(item["description"], item["price"])
        amount_row("Total", sub["total"], bold=True)

    pdf.ln(4)
    line("This request covers the remaining items on the receipt.")
    line(f"Prepared {date.today():%m/%d/%Y}", size=9)
    return bytes(pdf.output())

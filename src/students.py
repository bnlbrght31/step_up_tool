"""
Each child's SUFS student ID, per scholarship year, entered on the Students page.

SUFS issues a new student ID every scholarship year, so IDs are kept per year:
a note about last year's submission needs last year's ID. Saved in
students.json in the project folder, which is git-ignored: the repo is public
and student IDs must never be committed.

    {"students": [{"name": "Sam", "ids": {"2026-2027": "1234567"}}]}
"""

import json
import re
from pathlib import Path

from src import scholarship_year

STUDENTS_FILE = Path(__file__).resolve().parent.parent / "students.json"

# Files saved before IDs were kept per year held one ID per child. That format
# was only ever written during the 2026-27 scholarship year.
_LEGACY_YEAR = "2026-2027"


def current_year() -> str:
    """The scholarship year new IDs are saved under, e.g. "2026-2027"."""
    return scholarship_year.label(scholarship_year.start_year())


def _canon(name: str) -> str:
    """Comparable form of a name: 'ZIon ' and 'zion' are the same child."""
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def load_students(path: Path = STUDENTS_FILE) -> list[dict]:
    """[{"name", "ids": {year: id}}, ...] in saved order; [] if nothing is saved yet."""
    if not path.exists():
        return []
    rows = json.loads(path.read_text()).get("students", [])
    return [
        {"name": r["name"],
         "ids": dict(r["ids"]) if "ids" in r
         else ({_LEGACY_YEAR: r["student_id"]} if r.get("student_id") else {})}
        for r in rows
    ]


def save_students(rows: list[dict], path: Path = STUDENTS_FILE, year: str | None = None) -> list[dict]:
    """Save the Students form: each child's ID for `year` (default: this year).

    Trims values, drops blank rows and refuses a child listed twice. IDs saved
    for other years are kept; a child left off the form is removed. Returns the
    form's view of `year`: [{"name", "student_id"}].
    """
    year = year or current_year()
    existing = {_canon(s["name"]): s["ids"] for s in load_students(path)}
    saved, seen = [], set()
    for row in rows:
        name = re.sub(r"\s+", " ", (row.get("name") or "").strip())
        student_id = (row.get("student_id") or "").strip()
        if not name and not student_id:
            continue
        if not name:
            raise ValueError(f"Student ID {student_id} has no name next to it.")
        if _canon(name) in seen:
            raise ValueError(f"{name} is listed twice.")
        seen.add(_canon(name))
        ids = {y: i for y, i in existing.get(_canon(name), {}).items() if y != year}
        if student_id:
            ids[year] = student_id
        saved.append({"name": name, "ids": dict(sorted(ids.items()))})
    path.write_text(json.dumps({"students": saved}, indent=2) + "\n")
    return year_view(saved, year)


def year_view(rows: list[dict], year: str) -> list[dict]:
    """The Students form for one year: [{"name", "student_id"}]."""
    return [{"name": r["name"], "student_id": r["ids"].get(year, "")} for r in rows]


def student_id_for(name: str, rows: list[dict], year: str) -> str:
    """This child's saved student ID for `year`, or "" if none is saved."""
    wanted = _canon(name)
    return next((r["ids"].get(year, "") for r in rows if _canon(r["name"]) == wanted), "")


def canonical_name(name: str, rows: list[dict]) -> str:
    """The saved spelling of a child's name, or the name as typed if it isn't saved."""
    wanted = _canon(name)
    return next((r["name"] for r in rows if _canon(r["name"]) == wanted), (name or "").strip())


def names(rows: list[dict]) -> list[str]:
    return [r["name"] for r in rows]


def needing_new_ids(rows: list[dict], year: str) -> list[str]:
    """Children with an ID from another year but none yet for `year`: after the
    July rollover, the ones whose new ID still needs entering."""
    return [r["name"] for r in rows if r["ids"] and year not in r["ids"]]

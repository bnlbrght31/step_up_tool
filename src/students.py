"""
Each child's SUFS student ID, entered once on the Students page.

Kept in students.json in the project folder, which is git-ignored: the repo is
public and student IDs must never be committed.
"""

import json
import re
from pathlib import Path

STUDENTS_FILE = Path(__file__).resolve().parent.parent / "students.json"


def _canon(name: str) -> str:
    """Comparable form of a name: 'ZIon ' and 'zion' are the same child."""
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def load_students(path: Path = STUDENTS_FILE) -> list[dict]:
    """[{"name", "student_id"}, ...] in the order saved; [] if nothing is saved yet."""
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("students", [])


def save_students(rows: list[dict], path: Path = STUDENTS_FILE) -> list[dict]:
    """Save the Students form: trims values, drops blank rows, refuses duplicates."""
    cleaned, seen = [], set()
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
        cleaned.append({"name": name, "student_id": student_id})
    path.write_text(json.dumps({"students": cleaned}, indent=2) + "\n")
    return cleaned


def student_id_for(name: str, rows: list[dict]) -> str:
    """The saved student ID for this child, or "" if none is saved."""
    wanted = _canon(name)
    return next((r["student_id"] for r in rows if _canon(r["name"]) == wanted), "")

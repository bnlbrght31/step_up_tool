"""
The Step Up for Students scholarship year runs Jul 1 - Jun 30.

Every year-specific name and date in the app derives from here, so the July
rollover needs no code changes: the new year's Line Items tab is created on its
first submission, and scans and invoice downloads move to the new year on their
own. Values are read once when a module loads, so a running app picks up a
rollover on its next restart.
"""

from datetime import date
from pathlib import Path

# First year tracked in the "<year> Line Items" layout. The 2024-25 tab predates
# it (different columns) and is never read or written by the app.
FIRST_LINE_ITEMS_YEAR = 2025


def start_year(today: date | None = None) -> int:
    """Calendar year in which the scholarship year containing `today` began."""
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def label(year: int) -> str:
    """'2026-2027' for the year starting July 2026."""
    return f"{year}-{year + 1}"


def line_items_tab(year: int) -> str:
    return f"{label(year)} Line Items"


def gmail_date(year: int) -> str:
    """July 1 of `year` in Gmail's after: query format."""
    return f"{year}/07/01"


def receipts_folder(today: date | None = None) -> Path:
    """Where the year's receipts live: ~/Desktop/SUFS/<year label>/.

    The Amazon invoice downloader saves here and the receipts folder review
    reads it, so both move to the new year's folder each July.
    """
    return Path.home() / "Desktop" / "SUFS" / label(start_year(today))


def current_line_items_tab(today: date | None = None) -> str:
    """The tab new submissions are logged to."""
    return line_items_tab(start_year(today))


def all_line_items_tabs(today: date | None = None) -> list[str]:
    """Every Line Items tab, oldest first.

    Status scans and the Overview read all of them, so approvals and payments
    that arrive after a rollover still land on the prior year's rows. A tab that
    doesn't exist yet is skipped on read.
    """
    return [line_items_tab(y) for y in range(FIRST_LINE_ITEMS_YEAR, start_year(today) + 1)]

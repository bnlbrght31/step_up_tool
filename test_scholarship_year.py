"""
Tests for the single scholarship-year setting.

The Step Up scholarship year runs Jul 1 - Jun 30. Every year-specific name and
date in the app (the active Line Items tab, the scan start dates, the invoice
download folder) derives from src/scholarship_year.py, so the July rollover
needs no edits.

Run: python test_scholarship_year.py   (or: pytest test_scholarship_year.py)
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src import scholarship_year as sy


def test_year_starts_on_july_first():
    assert sy.start_year(date(2026, 6, 30)) == 2025
    assert sy.start_year(date(2026, 7, 1)) == 2026


def test_spring_belongs_to_the_year_that_started_the_previous_july():
    assert sy.start_year(date(2027, 1, 15)) == 2026


def test_labels_and_tab_names_match_the_sheet():
    assert sy.label(2026) == "2026-2027"
    assert sy.line_items_tab(2026) == "2026-2027 Line Items"


def test_gmail_dates_use_gmail_query_format():
    assert sy.gmail_date(2026) == "2026/07/01"


def test_current_values_match_what_was_hardcoded_before():
    """On today's date the derived values must equal the old constants exactly."""
    today = date(2026, 9, 26)
    assert sy.current_line_items_tab(today) == "2026-2027 Line Items"
    assert sy.all_line_items_tabs(today) == ["2025-2026 Line Items", "2026-2027 Line Items"]
    assert sy.gmail_date(sy.start_year(today)) == "2026/07/01"           # Amazon scan default
    assert sy.gmail_date(sy.FIRST_LINE_ITEMS_YEAR) == "2025/07/01"       # status scan start
    assert sy.label(sy.start_year(today)) == "2026-2027"                 # invoice folder


def test_rollover_adds_the_new_years_tab_and_keeps_the_old_ones():
    assert sy.all_line_items_tabs(date(2027, 7, 1)) == [
        "2025-2026 Line Items", "2026-2027 Line Items", "2027-2028 Line Items",
    ]
    assert sy.current_line_items_tab(date(2027, 7, 1)) == "2027-2028 Line Items"


def test_before_the_first_tracked_year_ends_there_is_one_tab():
    assert sy.all_line_items_tabs(date(2026, 3, 1)) == ["2025-2026 Line Items"]


def test_app_modules_take_their_year_values_from_the_shared_setting():
    """Guards against a hardcoded year creeping back into any consumer."""
    from src import amazon_scanner, pdf_downloader, sheets_logger, status_scan

    year = sy.start_year()
    assert sheets_logger.LINE_ITEMS_TAB == sy.current_line_items_tab()
    assert sheets_logger.LINE_ITEMS_TABS == sy.all_line_items_tabs()
    assert amazon_scanner.SCHOLARSHIP_START == sy.gmail_date(year)
    assert status_scan.AFTER_DATE == sy.gmail_date(sy.FIRST_LINE_ITEMS_YEAR)
    assert pdf_downloader.OUTPUT_DIR.name == sy.label(year)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} tests passed; the scholarship year rolls over on its own.")

"""
Web-friendly wrappers around the SUFS status scanners.

Each CLI scanner is split into:
  - preview(...)  scan Gmail + build updates + apply the default "skip rows that
                  already have a value" filter, returning the proposed changes
                  WITHOUT writing anything.
  - apply(...)    write a confirmed list of updates to the sheet.

Used by the /sufs-scan routes so the browser can show a preview and the user can
confirm before any write (same safety as the CLI's y/N prompt).
"""

from src import scholarship_year
from src.sheets_logger import (
    LINE_ITEMS_TABS as TESTING_TABS,
    batch_write_testing_status,
    read_testing_rows,
)
from src.sufs_email_scanner import (
    build_testing_status_updates,
    scan_approved_emails,
    scan_on_hold_emails,
    scan_paid_emails,
    scan_remittance_emails,
)

# Scan from the start of the first tracked year: every Line Items tab is read, so
# a late payment on any of them must still be found.
AFTER_DATE = scholarship_year.gmail_date(scholarship_year.FIRST_LINE_ITEMS_YEAR)


def _row_by_index(rows, idx, tab=None):
    # tab is part of a row's identity once we read across multiple year tabs.
    return next(
        (r for r in rows
         if r["row_index"] == idx and (tab is None or r.get("tab") == tab)),
        {},
    )


# ---------------------------------------------------------------------------
# Line Items tabs (all scholarship years): G=Status, J=On Hold, K=Approved, L=Paid
# Reads/writes across every tab in LINE_ITEMS_TABS; each row carries its source
# tab so writes route back to the correct year.
# ---------------------------------------------------------------------------

def preview_testing(overwrite=False):
    rows = read_testing_rows()
    on_hold = scan_on_hold_emails(after_date=AFTER_DATE)
    approved = scan_approved_emails(after_date=AFTER_DATE)
    paid = scan_paid_emails(after_date=AFTER_DATE)
    remittance = scan_remittance_emails(after_date=AFTER_DATE)

    updates = build_testing_status_updates(approved, on_hold, paid, remittance, rows)

    out = []
    for u in updates:
        row = _row_by_index(rows, u["row_index"], u.get("tab"))
        new_u = {
            "tab": u.get("tab"),
            "row_index": u["row_index"],
            "status": u.get("status", "") or "",
            "on_hold_date": u.get("on_hold_date", "") or "",
            "approved_date": u.get("approved_date", "") or "",
            "paid_date": u.get("paid_date", "") or "",
        }
        if not overwrite:
            if row.get("date_on_hold", "").strip():
                new_u["on_hold_date"] = ""
            if row.get("date_approved", "").strip():
                new_u["approved_date"] = ""
            if row.get("date_paid", "").strip():
                new_u["paid_date"] = ""
        if not any(new_u[f] for f in ("on_hold_date", "approved_date", "paid_date")):
            continue
        new_u["id"] = row.get("sufs_reimb_id", "")
        new_u["item"] = (row.get("item", "") or "")[:60]
        out.append(new_u)
    return {
        "tab": " + ".join(TESTING_TABS),
        "scanned": {"on_hold": len(on_hold), "approved": len(approved),
                    "paid": len(paid), "remittance": len(remittance)},
        "updates": out,
    }


def apply_testing(updates):
    clean = []
    for u in updates:
        item = {
            "tab": u.get("tab"),
            "row_index": int(u["row_index"]),
            "status": u.get("status", "") or "",
            "on_hold_date": u.get("on_hold_date", "") or "",
            "approved_date": u.get("approved_date", "") or "",
            "paid_date": u.get("paid_date", "") or "",
        }
        if any(item[f] for f in ("status", "on_hold_date", "approved_date", "paid_date")):
            clean.append(item)
    batch_write_testing_status(clean)
    return len(clean)


# Dispatch by tab key used in the URL ----------------------------------------
PREVIEW = {"testing": preview_testing}
APPLY = {"testing": apply_testing}

TAB_META = {
    "testing": {"title": "Line Items (" + " + ".join(TESTING_TABS) + ")",
                "cols": ["status", "on_hold_date", "approved_date", "paid_date"]},
}

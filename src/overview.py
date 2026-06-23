"""
Build/refresh a formatted "Overview" dashboard tab in the tracking sheet.

A glorified pivot of the 2025-2026 Line Items tab: count of line items and total
dollars in each status (Submitted / Approved / Paid / Other), broken out by child
with row + column totals, plus a "last updated" stamp set when the email scanner
runs. Recomputed from the live data each call, so the numbers are always current.
"""

import os
from collections import defaultdict
from datetime import datetime

import src.sheets_logger as sl

OVERVIEW_TAB = "Overview"

# Column groups (status label, row-status key). "Other" catches on-hold/denied/blank
# so the columns reconcile to the Total.
GROUPS = [("Submitted", "submitted"), ("Approved", "approved"),
          ("Paid", "paid"), ("Other", "__other__"), ("Total", "__total__")]
MAIN_STATUSES = {"submitted", "approved", "paid"}
NCOLS = 1 + 2 * len(GROUPS)  # Child + (Items,$) per group = 11

# --- colors ---------------------------------------------------------------
NAVY = {"red": 0.17, "green": 0.33, "blue": 0.51}
HEADER_BG = {"red": 0.89, "green": 0.91, "blue": 0.95}
TOTAL_BG = {"red": 0.94, "green": 0.95, "blue": 0.97}
WHITE = {"red": 1, "green": 1, "blue": 1}
GRAY = {"red": 0.45, "green": 0.45, "blue": 0.47}
BORDER = {"style": "SOLID", "color": {"red": 0.8, "green": 0.8, "blue": 0.82}}


def _sheet_id() -> str:
    # sheets_logger captures SHEET_ID at import; if that happened before .env was
    # loaded it's empty, so resolve it here at call time.
    if not sl.SHEET_ID:
        sl.SHEET_ID = os.environ.get("SUFS_SHEET_ID", "")
    return sl.SHEET_ID


def _price(s) -> float:
    s = str(s).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _canon_child(name) -> str:
    """Title-case so 'ZIon' and 'Zion' collapse to one child."""
    c = (name or "").strip()
    return c.title() if c else "(Unassigned)"


def _aggregate(rows):
    data = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
    for r in rows:
        child = _canon_child(r.get("student"))
        st = (r.get("status") or "").strip().lower()
        key = st if st in MAIN_STATUSES else "__other__"
        amt = _price(r.get("price"))
        for k in (key, "__total__"):
            data[child][k][0] += 1
            data[child][k][1] += amt
    return data


def _grid(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def _fmt(sid, r0, r1, c0, c1, cell_format, fields):
    return {"repeatCell": {
        "range": _grid(sid, r0, r1, c0, c1),
        "cell": {"userEnteredFormat": cell_format},
        "fields": "userEnteredFormat(" + fields + ")",
    }}


def _ensure_tab(svc, sheet_id_val):
    meta = svc.spreadsheets().get(spreadsheetId=sheet_id_val).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == OVERVIEW_TAB:
            return s["properties"]["sheetId"]
    res = svc.spreadsheets().batchUpdate(
        spreadsheetId=sheet_id_val,
        body={"requests": [{"addSheet": {"properties": {"title": OVERVIEW_TAB, "index": 0}}}]},
    ).execute()
    return res["replies"][0]["addSheet"]["properties"]["sheetId"]


def refresh_overview(scanned_at: datetime | None = None) -> dict:
    """Recompute the pivot and (re)write the formatted Overview tab."""
    book = _sheet_id()
    svc = sl._get_service()
    sid = _ensure_tab(svc, book)
    rows = sl.read_testing_rows()
    data = _aggregate(rows)

    # children: individuals first (alpha), shared ("&") buckets last
    children = sorted(data.keys(), key=lambda c: ("&" in c, c))
    keys = [g[1] for g in GROUPS]

    ts = (scanned_at or datetime.now()).strftime("%b %-d, %Y at %-I:%M %p")

    # --- value grid ---
    title_row = ["Reimbursement Overview"] + [""] * (NCOLS - 1)
    upd_row = [f"Last updated {ts}  ·  reflects your most recent email scan"] + [""] * (NCOLS - 1)
    blank = [""] * NCOLS
    grp_row = ["Child"]
    for label, _ in GROUPS:
        grp_row += [label, ""]
    sub_row = [""]
    for _ in GROUPS:
        sub_row += ["Items", "$"]

    child_rows = []
    for c in children:
        row = [c]
        for k in keys:
            row += [data[c][k][0], round(data[c][k][1], 2)]
        child_rows.append(row)

    grand = {k: [0, 0.0] for k in keys}
    for c in children:
        for k in keys:
            grand[k][0] += data[c][k][0]
            grand[k][1] += data[c][k][1]
    total_row = ["TOTAL"]
    for k in keys:
        total_row += [grand[k][0], round(grand[k][1], 2)]

    values = [title_row, upd_row, blank, grp_row, sub_row] + child_rows + [total_row]

    n = len(children)
    GRP, SUB = 3, 4                 # 0-based rows of the two header rows
    DATA0 = 5
    TOTAL = DATA0 + n               # 0-based total row
    BOTTOM = TOTAL + 1
    items_cols = [1, 3, 5, 7, 9]
    dollar_cols = [2, 4, 6, 8, 10]

    svc.spreadsheets().values().clear(spreadsheetId=book, range=OVERVIEW_TAB).execute()
    svc.spreadsheets().values().update(
        spreadsheetId=book, range=f"{OVERVIEW_TAB}!A1",
        valueInputOption="RAW", body={"values": values},
    ).execute()

    # --- formatting ---
    reqs = []
    meta = svc.spreadsheets().get(
        spreadsheetId=book, ranges=[OVERVIEW_TAB],
        fields="sheets(properties(sheetId),merges)").execute()
    for m in meta["sheets"][0].get("merges", []):
        reqs.append({"unmergeCells": {"range": m}})

    reqs.append({"mergeCells": {"range": _grid(sid, 0, 1, 0, NCOLS), "mergeType": "MERGE_ALL"}})
    reqs.append({"mergeCells": {"range": _grid(sid, 1, 2, 0, NCOLS), "mergeType": "MERGE_ALL"}})
    reqs.append({"mergeCells": {"range": _grid(sid, GRP, SUB + 1, 0, 1), "mergeType": "MERGE_ALL"}})
    for i in range(len(GROUPS)):
        c0 = 1 + 2 * i
        reqs.append({"mergeCells": {"range": _grid(sid, GRP, GRP + 1, c0, c0 + 2), "mergeType": "MERGE_ALL"}})

    reqs.append(_fmt(sid, 0, 1, 0, NCOLS,
                     {"backgroundColor": NAVY, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
                      "textFormat": {"foregroundColor": WHITE, "bold": True, "fontSize": 16}},
                     "backgroundColor,horizontalAlignment,verticalAlignment,textFormat"))
    reqs.append(_fmt(sid, 1, 2, 0, NCOLS,
                     {"horizontalAlignment": "CENTER",
                      "textFormat": {"foregroundColor": GRAY, "italic": True, "fontSize": 10}},
                     "horizontalAlignment,textFormat"))
    reqs.append(_fmt(sid, GRP, SUB + 1, 0, NCOLS,
                     {"backgroundColor": HEADER_BG, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
                      "textFormat": {"bold": True}},
                     "backgroundColor,horizontalAlignment,verticalAlignment,textFormat"))
    reqs.append(_fmt(sid, DATA0, BOTTOM, 0, 1,
                     {"horizontalAlignment": "LEFT", "textFormat": {"bold": False}},
                     "horizontalAlignment,textFormat"))
    reqs.append(_fmt(sid, TOTAL, BOTTOM, 0, NCOLS,
                     {"backgroundColor": TOTAL_BG, "textFormat": {"bold": True}},
                     "backgroundColor,textFormat"))
    for col in items_cols:
        reqs.append(_fmt(sid, DATA0, BOTTOM, col, col + 1,
                         {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"},
                          "horizontalAlignment": "CENTER"},
                         "numberFormat,horizontalAlignment"))
    for col in dollar_cols:
        reqs.append(_fmt(sid, DATA0, BOTTOM, col, col + 1,
                         {"numberFormat": {"type": "CURRENCY", "pattern": "\"$\"#,##0.00"}},
                         "numberFormat"))
    reqs.append({"updateBorders": {
        "range": _grid(sid, GRP, BOTTOM, 0, NCOLS),
        "top": BORDER, "bottom": BORDER, "left": BORDER, "right": BORDER,
        "innerHorizontal": BORDER, "innerVertical": BORDER}})
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 150}, "fields": "pixelSize"}})
    reqs.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 1, "endIndex": NCOLS},
        "properties": {"pixelSize": 90}, "fields": "pixelSize"}})
    reqs.append({"updateSheetProperties": {
        "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": SUB + 1}},
        "fields": "gridProperties(frozenRowCount)"}})

    svc.spreadsheets().batchUpdate(spreadsheetId=book, body={"requests": reqs}).execute()
    return {"children": n, "rows": len(rows), "updated": ts}

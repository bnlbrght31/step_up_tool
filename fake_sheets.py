"""
In-memory stand-in for the googleapiclient Sheets resource, shared by the tests.

Not named test_* so pytest never collects it. Supports just the surface the app
uses: values().get/append/update/batchUpdate, spreadsheets().get (metadata) and
spreadsheets().batchUpdate (deleteDimension, addSheet).
"""

import re


class _Exec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


class FakeSheets:
    """Minimal stand-in for the googleapiclient Sheets resource.

    Mimics two habits of the real API so tests catch the bugs they'd cause:
    it omits trailing empty cells (callers must pad short rows), and it honours
    row bounds in a range (A1:L500 really does stop at row 500).
    """

    def __init__(self, tabs: dict):
        self.tabs = tabs
        self.batch_requests = []   # spreadsheets().batchUpdate requests
        self.appends = []          # (tab, rows)
        self.updates = []          # (range, values)

    # -- api surface --------------------------------------------------------
    def spreadsheets(self):
        return self

    def values(self):
        return self

    @staticmethod
    def _parse(rng: str):
        """'Tab!A1:L500' -> (tab, first_col, last_col, first_row, last_row).

        Columns are 0-based; rows are 1-based and None when unbounded.
        """
        tab, _, spec = rng.partition("!")
        tab = tab.strip("'")
        m = re.match(r"([A-Z]+)(\d*)(?::([A-Z]+)(\d*))?$", spec)
        c0 = _col_index(m.group(1))
        c1 = _col_index(m.group(3)) if m.group(3) else c0
        r0 = int(m.group(2)) if m.group(2) else None
        if m.group(3):
            r1 = int(m.group(4)) if m.group(4) else None
        else:
            r1 = r0  # single cell like G13
        return tab, c0, c1, r0, r1

    def get(self, spreadsheetId=None, range=None, **kw):
        if range is None:  # spreadsheet metadata
            return _Exec({"sheets": [
                {"properties": {"sheetId": i, "title": t}}
                for i, t in enumerate(self.tabs)
            ]})
        tab, c0, c1, r0, r1 = self._parse(range)
        if tab not in self.tabs:
            raise RuntimeError(f"Unable to parse range: {tab}")
        rows = self.tabs[tab][(r0 or 1) - 1:r1]
        out = []
        for r in rows:
            padded = list(r) + [""] * (c1 + 1 - len(r))
            sliced = padded[c0:c1 + 1]
            while sliced and sliced[-1] == "":  # API drops trailing blanks
                sliced.pop()
            out.append(sliced)
        return _Exec({"values": out})

    def append(self, spreadsheetId=None, range=None, body=None, **kw):
        tab = self._parse(range)[0]
        self.appends.append((tab, body["values"]))
        self.tabs.setdefault(tab, []).extend(body["values"])
        return _Exec({})

    def update(self, spreadsheetId=None, range=None, body=None, **kw):
        tab, c0, _c1, r0, _r1 = self._parse(range)
        self.updates.append((range, body["values"]))
        target = self.tabs[tab][r0 - 1]
        while len(target) <= c0:
            target.append("")
        target[c0] = body["values"][0][0]
        return _Exec({})

    def batchUpdate(self, spreadsheetId=None, body=None, **kw):
        if "requests" in body:
            self.batch_requests.extend(body["requests"])
            for req in body["requests"]:
                if "deleteDimension" in req:
                    rng = req["deleteDimension"]["range"]
                    title = list(self.tabs)[rng["sheetId"]]
                    del self.tabs[title][rng["startIndex"]:rng["endIndex"]]
                if "addSheet" in req:
                    self.tabs.setdefault(req["addSheet"]["properties"]["title"], [])
        return _Exec({})

    # -- assertions helpers -------------------------------------------------
    def deletions(self):
        return [r for r in self.batch_requests if "deleteDimension" in r]

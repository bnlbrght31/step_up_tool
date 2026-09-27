# Receipt folder review — design

Status: approved in conversation 2026-09-27; this document is for final review.

## Goal

One button that makes the **Unsubmitted** tab a complete to-do list. Every
receipt in the current year's folder ends up either submitted (in a Line Items
tab) or staged (in Unsubmitted), so nothing sits in the folder untracked, and
the Remove/Keep prompt on the confirm page works when each one is later
submitted.

Today the folder (`~/Desktop/SUFS/2026-2027/`) holds 42 Amazon invoice PDFs
from the downloader, hand-named PDFs (`ikea-bookshelf.pdf`), and phone photos
that were converted by hand into a PDF of the same name. A dry run against the
live sheet sorted its 54 receipts into 38 staged, 4 submitted and 12 untracked.

## Decisions

| Question | Decision |
|---|---|
| Surface | A new app page, "Review receipts folder", linked from the home page. |
| Row contents for a new receipt | Claude reads the receipt and fills Item, Store, Price and Date Purchased. |
| Receipts not being submitted | A **Not submitting** action moves the receipt's files into `Not submitting/`, so they are never offered again. |
| Photo originals after conversion | Moved into `Originals/`; the PDF takes the photo's place. |
| Conversion size | Long edge 2200 px, JPEG quality 75, colour, phone rotation applied. A 4.2 MB, 24 MP phone photo becomes a ~480 KB PDF, with every line of the receipt legible. |

## Folder layout

```
~/Desktop/SUFS/<scholarship year>/      reviewed (top level only)
    111-7705354-6743464.pdf
    IMG_1698.pdf
    Originals/                          ignored by the review
        IMG_1698.jpeg
    Not submitting/                     ignored by the review
        111-4080584-5227408.pdf
```

The folder path comes from `scholarship_year.receipts_folder()`, a new function
that `pdf_downloader.OUTPUT_DIR` also uses, so the downloader and the review
always agree on the folder and both roll over each July.

## What counts as a receipt

- A receipt is a **name**: every top-level file sharing a normalised name is one
  receipt. Normalisation is the existing `_normalize_reference` (case, outer
  whitespace, and spaces vs underscores ignored), so `IMG_1698.jpeg` and
  `IMG_1698.pdf` are one receipt.
- The receipt's **reference** is the file name without its extension, as it
  appears on disk (the PDF's name when both exist). This is what goes into the
  Order/Receipt # column.
- Supported types: `.pdf`, and images `.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`
  (case-insensitive). Files starting with `.` (e.g. `.DS_Store`) are ignored.
  Any other file is listed as **Can't process** with its extension as the
  reason.
- A receipt has a **kind**: `pdf` (PDF only), `photo` (images only) or
  `photo+pdf` (both).

## Classification

Each receipt gets exactly one status, in this precedence:

1. **submitted** — its reference matches the Invoice column (file name without
   extension) of a row in any Line Items tab.
2. **staged** — its reference matches the Order/Receipt # column of a row in
   Unsubmitted.
3. **untracked** — neither.

Receipts whose only files are unsupported are **unsupported**.

## Page and flow

The page loads the review from the server and shows four groups: **Untracked**
(expanded, each row checked by default, with a **Not submitting** button),
**Staged**, **Submitted** and **Can't process** (collapsed, counts shown).

**Not submitting** moves every file of that receipt into `Not submitting/` and
removes the row. Only untracked receipts can be skipped.

**Add N to Unsubmitted** processes the checked receipts one request at a time.
The button is disabled for the whole batch. Each row shows its progress and
result; the batch ends with a summary: how many were added, how many need
details, and the total Claude cost.

For each receipt, the server:

1. Re-reads the sheet and stops with `already_tracked` if the receipt is now
   staged or submitted.
2. Makes sure a PDF exists. If the receipt is `photo`, the first image (sorted
   by name) is converted to `<reference>.pdf`. If it is `photo+pdf`, the
   existing PDF is used unchanged.
3. Reads the PDF with the existing `parse_receipt`.
4. Appends one Unsubmitted row (mapping below).
5. Moves every image of the receipt into `Originals/`.

This order means a failure partway leaves at most a new PDF beside the photo,
which the next review treats as a `photo+pdf` receipt.

### Unsubmitted row mapping

| Column | Value |
|---|---|
| Student | blank |
| Item | first line item's description; if there are more, `" + N more"` is appended |
| Store | first line item's vendor |
| Order/Receipt # | the receipt's reference |
| Price | receipt grand total, else the computed total, as `0.00` |
| Date Purchased | first line item's purchase date |
| Status | blank |

If Claude can't read the receipt — the call fails, or it returns no line
items — the row is appended with only the Order/Receipt # filled, and the
result is flagged `needs_details`.

## Components

**`src/receipt_folder.py`** — folder logic only; no sheet or Claude calls.
- `review(folder, submitted_refs, staged_refs)` → the receipts, grouped and
  classified.
- `to_pdf(image_path)` → writes `<stem>.pdf` beside the image and returns its
  path. Refuses to overwrite an existing file.
- `move_into(folder, subfolder, paths)` → moves files into the subfolder,
  creating it; a name clash gets `" (2)"`, `" (3)"`, … before the extension.
- `row_from_parse(reference, items, reconciliation)` → the Unsubmitted row.

**`src/receipt_routes.py`** — a blueprint, like `submission_routes.py`, so it can
be tested without importing the browser agent.

| Route | Purpose |
|---|---|
| `GET /receipts` | the page |
| `GET /receipts/review` | JSON: folder path and every receipt with reference, files (name, size), kind and status |
| `POST /receipts/skip` `{reference}` | moves the receipt to `Not submitting/`. 404 if no such receipt, 409 if not untracked |
| `POST /receipts/add` `{reference}` | runs the five steps above. Returns `added` or `already_tracked`, the row written, whether it converted, `needs_details`, and cost. 404 if no such receipt, 422 if conversion fails, 500 if the sheet write fails |

Both POST routes take a **reference**, never a path. The server finds the
files by scanning the folder, so no request can reach a file outside it.

**`src/sheets_logger.py`**
- `append_unsubmitted(rows)` — appends staged rows for any store. The existing
  `append_orders` becomes a caller of it with the store set to Amazon, removing
  its hardcoded row builder.
- `read_tracked_references()` → `(submitted_refs, staged_refs)`, read
  **strictly**: it lists the sheet's tabs first, reads only the Line Items tabs
  that exist, and raises on any read error. The existing readers skip a tab when
  its read fails; here that would make every receipt look untracked and offer to
  re-add all of them.

**`templates/receipts.html`** — the page, in the shared ledger styles.
**`templates/index.html`** — a home-page card linking to it.

## Error handling

| Failure | Result |
|---|---|
| Sheet can't be read during review | The page shows the error and no receipts. Nothing is classified. |
| Receipt already staged or submitted when added | `already_tracked`; nothing written or moved. |
| Image can't be converted (corrupt, or HEIC support missing) | 422; nothing written or moved; the row shows the reason. |
| Claude can't read the receipt | Row appended with only the reference; `needs_details`. |
| Sheet append fails | 500; the new PDF (if any) stays; nothing moved. |
| Move destination already has that name | The moved file gets a `" (2)"` suffix; nothing is overwritten. |

Nothing is ever deleted.

## Testing

A new `test_receipt_folder.py`, runnable directly or with pytest. Everything runs
in temporary folders against `FakeSheets`, with `parse_receipt` stubbed, so no
test reads the real folder, writes the real sheet or calls Claude.

- Grouping: `photo+pdf` pairs count once; subfolders and hidden files are
  ignored; unsupported files are listed with a reason.
- Classification precedence: submitted over staged over untracked, including a
  submitted Invoice with a different extension.
- `to_pdf`: a 24 MP image produces a PDF under 1 MB whose long edge is 2200 px;
  EXIF rotation is applied; a smaller image is not upscaled; HEIC converts; an
  existing PDF is never overwritten.
- `move_into`: all of a receipt's files move; a name clash is suffixed, not
  overwritten.
- Add: converts, appends the mapped row and moves the photo; a second add is
  `already_tracked` with no second row; a failed Claude read appends a
  reference-only row; a failed conversion writes and moves nothing.
- Review: a sheet read error surfaces as an error, not an all-untracked list; a
  missing (future) Line Items tab is not an error.
- Routes: a reference containing `../` or naming no receipt returns 404 and
  moves nothing; skip on a staged receipt returns 409.

## Dependencies

`pillow-heif` for HEIC (a Python 3.14 macOS wheel exists). `Pillow` is already
installed through `pdfplumber` and becomes an explicit requirement because the
app now uses it directly.

## Out of scope

- **Cross-reference note PDF** for a receipt split across children. This is a
  separate feature, designed next: it changes the existing upload → confirm
  flow.
- Re-compressing existing PDFs. The review never rewrites a PDF it didn't
  create; the four hand-made 4 MB PDFs stay as they are.
- Moving the photo of an already staged or submitted `photo+pdf` receipt into
  `Originals/`. Photos move only as part of Add.
- Filling the Student column. The receipt doesn't say which child it is for.

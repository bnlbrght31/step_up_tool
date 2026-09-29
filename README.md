# SUFS Reimbursement Agent

A local web app that takes Step Up for Students reimbursements from receipt to
payment, and keeps a Google Sheet tracking every one of them:

1. **Receipt parser** — reads a receipt PDF with Claude and fills out the SUFS
   reimbursement form in Chrome for you. It never submits; you review and submit.
   Then it logs each line item to your tracking sheet with one click.
2. **Amazon order scanner** — finds Amazon orders in Gmail, flags the
   SUFS-eligible ones, marks returns, downloads invoice PDFs and stages the
   orders in your sheet's **Unsubmitted** tab.
3. **Receipts folder review** — checks this year's receipts folder for anything
   not yet submitted or staged, converts phone photos to small PDFs and stages
   them too, so Unsubmitted stays a complete to-do list.
4. **Receipts split across children** — remembers which items on a receipt were
   already submitted for which child, and makes a note PDF (with each child's
   SUFS student ID) to attach to the next child's submission.
5. **SUFS status scanner** — reads SUFS approval, on-hold and payment emails and
   writes each line item's status and dates back to the sheet, plus a formatted
   **Overview** dashboard tab.

Finished receipts are filed into a `Submitted/` subfolder as you go, and the
scholarship-year rollover each July needs no changes.

---

## What you'll need

- A Mac or Windows PC
- Google Chrome
- An Anthropic API key (one-time, see below)
- Python 3.11 or newer

---

## One-time setup

You only need to do this once.

### 1. Get an Anthropic API key

1. Go to [console.anthropic.com](https://console.anthropic.com) and create an account
2. Click **API Keys** in the left sidebar
3. Click **Create Key**, give it a name, and copy the key — it starts with `sk-ant-...`

### 2. Create your `.env` file

In the project folder, create a file called `.env` (no other name, just `.env`) and paste this inside:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
SUFS_SHEET_ID=your-google-sheet-id-here
```

Replace each value with your actual key / sheet ID. The sheet ID is the long string in your Google Sheet URL between `/d/` and `/edit`.

> **Mac:** Open TextEdit, go to **Format → Make Plain Text**, paste the line above, then save it as `.env` in the project folder. Make sure it doesn't save as `.env.txt`.
>
> **Windows:** Open Notepad, paste the line above, then go to **File → Save As**. Set "Save as type" to **All Files**, name it `.env`, and save it in the project folder.

### 3. Install dependencies

#### Mac

Open **Terminal**, navigate to the project folder, and run these commands one at a time:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

#### Windows

Open **Command Prompt**, navigate to the project folder, and run these commands one at a time:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 4. Set up your SUFS Chrome window (one-time)

The agent needs Chrome to run with remote debugging enabled. This requires a separate Chrome profile — but you can sync all your bookmarks and passwords to it by signing into your Google account.

#### Mac

Run this command in Terminal:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.sufs-agent-chrome"
```

#### Windows

Run this command in Command Prompt:

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.sufs-agent-chrome"
```

> If Chrome is installed in a different location, adjust the path accordingly.

When Chrome opens:
1. Sign into your Google account
2. Turn on sync (click your profile photo → **Turn on sync** → **Yes, I'm in**)
3. Sign into the [Step Up for Students portal](https://apply.stepupforstudents.org)

> You only need to do this once. The next time you launch with the same command, you'll already be logged in.

### 5. (Optional) Create a shortcut to launch SUFS Chrome

#### Mac

Add this line to your `~/.zshrc` file:

```bash
alias sufs-chrome='/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.sufs-agent-chrome"'
```

Then run `source ~/.zshrc`. From now on, just type `sufs-chrome` in Terminal.

#### Windows

Create a file called `sufs-chrome.bat` anywhere convenient (e.g. your Desktop) with this content:

```
@echo off
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.sufs-agent-chrome"
```

Double-click it to launch SUFS Chrome.

### 6. Google Sheets access

Logging to your tracking sheet uses a Google Cloud **service account**:

1. Save the service account's JSON key as `service_account.json` in the project
   folder (git-ignored — never committed).
2. Share your tracking spreadsheet with the service account's email as an **Editor**.
3. Put the sheet's ID in `.env` as `SUFS_SHEET_ID=...` (step 2 above).

### 7. Gmail access (for the Amazon and SUFS status scanners)

The scanners read Gmail read-only through OAuth. Authorize once:

```bash
python authorize_gmail.py
```

A browser window asks you to sign in and allow read-only Gmail access. The token
is saved to `token.json` (git-ignored). If it ever expires, click **Re-authorize
Gmail** on the app's home page.

---

## Every-time usage

### Step 1 — Launch SUFS Chrome

**Mac:** Run `sufs-chrome` in Terminal (or paste the full command from Step 4).

**Windows:** Double-click `sufs-chrome.bat` (or paste the full command from Step 4 into Command Prompt).

### Step 2 — Open your reimbursement request

In the SUFS Chrome window:
1. Go to the Step Up for Students portal
2. Navigate to your reimbursement request and open the form where you add line items
3. Upload the receipt on the SUFS site first (they require this)

### Step 3 — Start the app

**Mac, the easy way:** double-click `launch.command` in the project folder. It
opens SUFS Chrome (if it isn't already running), starts the app, and opens the
app as a tab in SUFS Chrome, so you can skip Step 1 and Step 4. Keep its Terminal
window open while you work; closing it stops the app. It can also be wrapped in
a Desktop app icon (see `assets/applet.applescript`).

**Or by hand:** open a **second** Terminal (Mac) or Command Prompt (Windows) window, navigate to the project folder, and run:

**Mac:**
```bash
source .venv/bin/activate
python main.py
```

**Windows:**
```
.venv\Scripts\activate
python main.py
```

You should see something like `Running on http://127.0.0.1:5054`. Leave this window open.

> **After updating the app's code, restart it** (close that window and launch
> again). The app doesn't reload itself, so a running copy keeps the old code.

### Step 4 — Open the app in your browser

Go to [http://127.0.0.1:5054](http://127.0.0.1:5054) in any browser (your regular Chrome is fine).

### Step 5 — Discover form options (first time per reimbursement session)

On the app's home page, click **Discover** with the SUFS form open in your SUFS Chrome window. This takes about 30 seconds and teaches the agent all the available dropdown options (category, type, description, vendor). You'll see a green "✓ Discovered" badge when it's done.

> You only need to do this once per session — not every receipt.

### Step 6 — Upload your receipt

Choose your receipt PDF, then click **Parse receipt**. Claude reads the receipt and extracts each line item.

If you've logged this exact file before (for another child), the app reuses
what it read last time instead of reading it again — see
[Receipts split across children](#receipts-split-across-children).

### Step 7 — Review the extracted items

You'll see a list of items pulled from the receipt. For each one you can:
- **Edit any field** by clicking on it
- **Uncheck** items you don't want to include
- Choose the correct **category, type, description, and vendor** from the dropdowns

> The **Description** dropdown shows generic options (like "Books/Textbooks/Workbooks") — this is correct. The SUFS form uses broad categories, not individual item names.

A banner compares the items' total with the receipt's printed total, and any
category the app wasn't sure about is badged for a quick check. If this receipt
was already submitted for another child, an **Already submitted for another
child** panel appears too, and the items already submitted start unchecked.

### Step 8 — Fill the form

Click **Fill Form**. Switch to your SUFS Chrome window and watch it fill in the fields. When it's done:

1. **Review everything carefully** in Chrome
2. Make any corrections by hand
3. **Submit the form yourself** — the agent never submits

### Step 9 — Log the submission to your tracking sheet

After SUFS shows the confirmation page with your reimbursement ID:

1. Switch back to the app — a **Log Submission to Sheet** panel will have appeared
2. Pick the child — one button per child saved on the **Students** page, or
   **Other…** to type a name — and enter the **SUFS Reimbursement ID** from the
   confirmation page. A typed name that matches a saved child (in any
   capitalization) is logged with the saved spelling.
3. Click **Log to Sheet**

This writes one row per line item to the current scholarship year's Line Items
tab (e.g. `2026-2027 Line Items`, created automatically on the first submission of
the year) with:
- All item details (description, vendor, price with tax, purchase date, invoice filename)
- Status set to `submitted`
- Today's date in Date Submitted
- Line item IDs like `12345678-1`, `12345678-2`, etc.

Each reimbursement ID can be logged only once: the button locks after a
successful log, and the app refuses an ID that's already in any year's tab, so a
double-click can't duplicate rows.

### Step 10 — Clear the order out of Unsubmitted

If the purchase is staged on the **Unsubmitted** tab, a prompt appears right
after logging:

- **Remove from Unsubmitted** — deletes that staged row. Use this once the order
  is fully reimbursed.
- **Keep it — more kids to submit** — leaves the row and stamps its Status
  column with `partial: <student> <reimbursement id> (MM/DD)`. Use this when the
  same order still needs submitting for another child; the note accumulates, and
  the prompt shows it back to you next time so you can see who's already done.

Nothing is ever removed automatically — the same purchase is often reimbursed
once per child, so only you know when the last one is done.

**Filing the receipt.** Once a receipt is finished, its file moves from this
year's folder (`~/Desktop/SUFS/<year>/`) into a `Submitted/` subfolder, so the
folder only holds receipts still to do. That happens right after logging when
the receipt isn't in Unsubmitted, or when you choose **Remove from
Unsubmitted**. **Keep it — more kids to submit** leaves the file where it is
for the next child's upload. If the file isn't in the year folder (say you
uploaded it from Downloads), nothing moves, and a failed move never undoes the
log.

**Matching.** A staged row is found by its **Order/Receipt #** column. Amazon
rows get that filled in by the scanner. For any other vendor, paste your own
reference into that column when you add the row by hand, then name the receipt
PDF the same thing — `Target 8-14-26` in the column, `Target 8-14-26.pdf`
uploaded. The match ignores case, surrounding spaces, the difference between
spaces and underscores, and the punctuation and accents the upload page strips
from file names (`Lowe's 8-1-26.pdf` is uploaded as `Lowes_8-1-26.pdf`), but is
otherwise exact: `Target` will not match `Target 8-14-26`. If nothing matches,
no prompt appears and nothing changes.

---

## Review receipts folder

Keeps the **Unsubmitted** tab a complete to-do list. On the home page, click
**Review receipts folder**. The app looks at this year's folder
(`~/Desktop/SUFS/<year>/`, the same one Amazon invoices download to) and sorts
every receipt into:

- **Untracked**: not submitted and not in Unsubmitted
- **Staged in Unsubmitted**
- **Submitted**: in a Line Items tab
- **Can't process**: a file type it doesn't handle

A receipt is a file *name*, so `IMG_1698.jpeg` and `IMG_1698.pdf` count once.

For untracked receipts:

- **Add to Unsubmitted** stages the checked ones. A photo (`.jpg`, `.png`,
  `.heic`) is first converted to a PDF of the same name, at about 480 KB instead
  of about 4 MB, and the photo moves to `Originals/`. Claude then reads the
  receipt and fills in the item, store, price and purchase date. If it can't
  read one, the row is added with just the file name for you to fill in.
- **Not submitting** moves the receipt's files to `Not submitting/`, so it
  isn't offered again. Drag it back out to undo.

If any receipts in the **Submitted** group are finished, meaning they're in a
Line Items tab and no longer in Unsubmitted, a **Move N to Submitted/** button
files them. It catches receipts logged before automatic filing existed, or
uploaded from somewhere other than the year folder. Receipts still in
Unsubmitted have more kids to submit and stay put.

Nothing is ever deleted. Later, when you upload one of these receipts on the
intake page and log it, the Remove/Keep prompt finds its Unsubmitted row by
file name, and the finished receipt is filed in `Submitted/`. The review
ignores all three subfolders (`Originals/`, `Not submitting/`, `Submitted/`).

---

## Receipts split across children

When one receipt is reimbursed separately for each child, SUFS reviewers need to
see what was already claimed from it. After the first child's submission is
logged, uploading the same receipt again for the next child shows an
**Already submitted for another child** panel on the review page, listing each
earlier submission. **Download note (PDF)** saves a one-page note naming each
earlier submission's child, SUFS student ID, reimbursement ID and items. Attach
it to the new submission alongside the receipt.

Enter each child's SUFS student ID on the **Students** page (home page →
Students). The IDs are saved on this computer only, in `students.json`, which is
git-ignored. A child with no saved ID shows as "not on file" in the note until
you add it.

**SUFS issues new student IDs every scholarship year**, so the page edits the
current year's IDs and keeps earlier years'. After July 1 it asks for any new
IDs that haven't been entered yet. A note uses each earlier submission's ID from
the year it was submitted, so a June submission keeps last year's ID even after
the rollover.

The earlier submission is found by the receipt's file name, so upload the same
file each time.

**Items already submitted start unchecked.** When you log a receipt, the app
remembers its items as you confirmed them and which ones went to which child,
in `receipt_history.json` on this computer only (git-ignored, since it holds
purchase details). Uploading the same file again reuses that saved reading —
same items in the same order, with no second Claude read — and every item
already submitted starts unchecked, labeled "Submitted for Sam · 12345678".
Re-check an item if you really mean to include it again. Receipts are matched by
the file's contents, so a renamed copy still matches, but an edited or
re-exported file is read fresh. Receipts logged before this existed aren't
remembered until their next log.

---

## SUFS Status Scanner

After SUFS sends approval, on-hold, or payment emails, click **SUFS statuses —
Line Items** on the home page, then **Scan emails**. The app shows every change
it would make; nothing is written until you click **Write update(s) to the
sheet**. (From a terminal, `python scan_testing_status.py` does the same with a
yes/no prompt.)

It scans Gmail for:
- **On-hold emails** → sets Status = `on hold`, writes Date On Hold
- **Approval emails** → sets Status = `approved`, writes Date Approved
- **Payment/Remittance emails** → sets Status = `paid`, writes Date Paid

Each email is downloaded and read only once. What it said is saved in
`email_scan_cache.json` on this computer (git-ignored), so later scans download
only emails that are new and finish in seconds. The cache resets itself when the
email-reading code changes, and deleting it is always safe; the next scan just
reads everything again. If Gmail briefly refuses requests ("Quota exceeded" or a
dropped connection), the scan waits and retries instead of failing.

The scanner matches emails to sheet rows using the reimbursement ID and dollar
amount across every scholarship year's tab, so late payments on last year's rows
still land. It's safe to re-run — rows that already have a date are skipped.
Check **Overwrite values that already exist** (or pass `--overwrite` on the
command line) to force-update them.

Each scan run from the app also rebuilds the **Overview** tab: line items and
dollars per child in each status (Submitted / Approved / Paid / Other), with a
"last updated" stamp.

---

## Amazon Order Scanner

On the home page, click **Scan Amazon orders**. It needs Gmail and Google
Sheets access from One-time setup steps 6 and 7.

1. The scanner opens at [http://127.0.0.1:5054/scan](http://127.0.0.1:5054/scan)
2. The **Scan from** date defaults to your last scan date (or July 1 of the current scholarship year on first run). Change it if you want to go further back.
3. Click **Scan Gmail** — this searches for Amazon order confirmation emails and checks each item for SUFS eligibility using Claude. Takes 30–60 seconds depending on how many emails are found.
4. Review the results table:
   - **Green** badge = flagged as SUFS-eligible
   - **Purple** badge = already in your tracking sheet
   - **Red** badge = item was returned
   - **Yellow** badge = partial return (hover to see which item)
   - Use **Show Eligible Only** to hide ineligible and already-logged rows
5. Check the boxes for items you want to log, then click:
   - **Log to Sheet + Download PDFs** — appends to your Google Sheet and downloads invoice PDFs to this year's folder (`~/Desktop/SUFS/<year>/`, e.g. `2026-2027`) via the SUFS Chrome window. Existing PDFs are skipped.
   - **Log to Sheet Only** — appends to the sheet without downloading PDFs (use when Chrome isn't open)
6. The scan date updates automatically after logging so the next scan picks up from today.

Logged orders go to the **`Unsubmitted`** tab (created automatically on first
log), one row per order — these are staged purchases you haven't filed with SUFS
yet, so there are no per-line-item IDs. The `Unsubmitted` tab is shared across
scholarship years. Once you submit a reimbursement, the receipt flow writes the
line items to the current year's Line Items tab (`2026-2027 Line Items`).

> The scanner never submits anything to SUFS — it only reads Gmail and writes to your own spreadsheet.

---

## Rolling over to a new scholarship year

The scholarship year runs **July 1 – June 30**. Each year's submitted line items
live in their own tab (e.g. `2025-2026 Line Items`, `2026-2027 Line Items`). The
shared **`Unsubmitted`** staging tab carries over — it isn't year-specific.

Nothing needs editing when a new year starts — every year-specific name and date
comes from `src/scholarship_year.py`, which works out the current year from
today's date. After July 1 (and an app restart):

- New submissions log to the new year's tab, created on its first submission.
- The status scanner and Overview keep reading every year's tab, so late
  approvals and payments on the prior year still land.
- The Amazon scanner's default start date and the invoice download folder
  (`~/Desktop/SUFS/<year>/`) move to the new year.

The one fixed value is `FIRST_LINE_ITEMS_YEAR` (2025): the older `2024-25` tab uses
a different layout and the app never reads it.

---

## Purchasing guides

`docs/purchasing_guide_reference.md` is the only guide content the app reads. It's
inlined into the Claude prompts in `src/receipt_parser.py` (categorization) and
`src/amazon_scanner.py` (eligibility screening), so keeping it accurate and compact
matters. Both send it as a cached prompt block, so repeat calls within the cache
window read it at a fraction of the price instead of paying for it in full.

SUFS revises the guides annually (usually effective July 1, with amendments after).
When they do, rewrite that markdown file from the current sources:

- **FES-UA** — PDF from the Florida Center for Students with Unique Abilities:
  <https://fcsua.org/docs/fesua/2026-27-purchasing-english.pdf>, with a changes summary at
  <https://fcsua.org/docs/fesua/2026-27-changes-summary-english.pdf>
- **PEP** — **web-only as of 2026-27**:
  <https://www.stepupforstudents.org/handbook-web/pep-purchasing-guide/>. The old
  `go.stepupforstudents.org/hubfs/GUIDES/PEP-Purchasing-Guide.pdf` URL still resolves but
  serves the stale 2025-26 file — don't use it.

Copies of the sources live in `docs/sources/` (gitignored, since `*.pdf` is), with the
prior year kept under `docs/sources/archive-2025-26/`.

After rewriting, re-check the category names the guide emits against `form_options.json` —
the parser's labels are snapped to real dropdown values by `src/option_match.py`, and a
category that matches nothing silently leaves the form field blank.

---

## Your data stays on this computer

The repo is public, so everything personal lives in local files that git ignores:

| File | Holds |
|---|---|
| `.env` | Anthropic API key, sheet ID |
| `service_account.json`, `token.json` | Google Sheets and Gmail credentials |
| `students.json` | each child's SUFS student ID, per scholarship year |
| `receipt_history.json` | which receipt items went to which child |
| `email_scan_cache.json` | what each SUFS status email said |

Uploaded receipts are deleted from the app's temp folder as soon as they're read.
`test_repo_privacy.py` fails if a real-looking Amazon order number or a
`/Users/<name>` path is ever committed, and `students.json`,
`receipt_history.json` and `email_scan_cache.json` each have a test that fails
if they stop being git-ignored.

---

## Running the tests

Every test runs offline against fakes (a fake Google Sheet, fake Gmail,
temporary folders and a stubbed Claude), so none of them touch your real sheet,
receipts folder, Gmail or API bill:

```bash
source .venv/bin/activate
for t in test_*.py; do python "$t" | tail -1; done
```

Each file prints `OK — N tests passed; …` when everything passes.

---

## Troubleshooting

**Changes don't show up after an update**
Restart the app: close the Terminal window running it, then launch it again.

**Gmail "Quota exceeded … Units per minute per user" (403)**
Gmail briefly refuses requests when they come too fast. The scanners wait and
retry automatically, and status scans only download emails they haven't read
before, so this should be rare. If it still happens, wait a minute and scan again.

**"Gmail not authorized"**
Click **Re-authorize Gmail** on the home page, or run `python authorize_gmail.py`.

**"Failed to connect to Chrome"**
Make sure the SUFS Chrome window is open and you launched it with the `--remote-debugging-port=9222` flag. Regular Chrome windows won't work.

**"No SUFS tab found"**
Make sure the reimbursement form is open as a tab in the SUFS Chrome window before clicking Fill Form.

**Items aren't filling correctly**
Run **Discover** again with the form open, then retry. This re-maps the dropdown options and usually fixes it.

**The app won't start (Mac)**
Make sure you activated the virtual environment first: `source .venv/bin/activate`

**The app won't start (Windows)**
Make sure you activated the virtual environment first: `.venv\Scripts\activate`

**"python" not found (Mac)**
Try `python3` instead of `python`.

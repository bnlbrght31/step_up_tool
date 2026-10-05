# SUFS Reimbursement Agent

A local web app that takes Step Up for Students (SUFS) reimbursements from
receipt to payment, and keeps a Google Sheet tracking every one of them.

**It never submits anything to SUFS.** It fills the form; you check it and
click Submit yourself.

What it does:

1. **Fills the SUFS form from a receipt.** Claude reads a receipt PDF, you
   check the items, and the app types them into the SUFS form in Chrome. After
   you submit, one click logs each line item to your tracking sheet.
2. **Finds Amazon orders.** It searches Gmail for Amazon orders, flags the
   SUFS-eligible ones, marks returns, downloads invoice PDFs, and adds the
   orders to your sheet's **Unsubmitted** tab (your to-do list).
3. **Reviews your receipts folder.** It finds receipts in this year's folder
   that aren't submitted or on the to-do list yet, shrinks phone photos into
   small PDFs, and adds them to **Unsubmitted** too.
4. **Handles receipts split across children.** It remembers which items on a
   receipt were already submitted for which child, and makes a note PDF to
   attach to the next child's submission.
5. **Tracks SUFS statuses.** It reads SUFS approval, on-hold and payment emails,
   writes each line item's status and dates back to the sheet, and keeps an
   **Overview** tab up to date.

Finished receipts are moved into a `Submitted/` subfolder as you go, and the
switch to a new scholarship year each July happens on its own.

## Contents

- [A typical session](#a-typical-session)
- [One-time setup](#one-time-setup)
- [Starting the app](#starting-the-app)
- [Submitting a receipt](#submitting-a-receipt)
- [Review receipts folder](#review-receipts-folder)
- [Receipts split across children](#receipts-split-across-children)
- [SUFS status scanner](#sufs-status-scanner)
- [Amazon order scanner](#amazon-order-scanner)
- [A new scholarship year](#a-new-scholarship-year)
- [Purchasing guides](#purchasing-guides)
- [Your data stays on this computer](#your-data-stays-on-this-computer)
- [Running the tests](#running-the-tests)
- [Troubleshooting](#troubleshooting)

---

## A typical session

Once setup is done, a session looks like this:

1. **Start the app.** Double-click **SUFS Agent** on the Desktop (Mac). It opens
   the SUFS Chrome window with the app in a tab.
2. **Open the SUFS form.** In that Chrome window, open your reimbursement
   request and upload the receipt on the SUFS site.
3. **Parse the receipt.** In the app tab, drop in the same receipt PDF and click
   **Parse receipt**.
4. **Check the items**, then click **Fill form**.
5. **Review the SUFS form in Chrome and submit it yourself.**
6. **Log it.** Back in the app, pick the child, type the SUFS reimbursement ID,
   and click **Log to sheet**.

Every so often, also run the scanners from the home page: **Scan Amazon
orders**, **Review receipts folder**, and **SUFS statuses — Line Items**.

---

## One-time setup

You only do this once per computer.

### What you'll need

- A Mac or Windows PC
- Google Chrome
- Python 3.11 or newer
- An Anthropic API key (step 1)
- A Google Sheet for tracking, plus Google Cloud credentials for Sheets and
  Gmail (steps 6 and 7)

### 1. Get an Anthropic API key

1. Go to [console.anthropic.com](https://console.anthropic.com) and create an
   account.
2. Click **API Keys** in the left sidebar.
3. Click **Create Key**, give it a name, and copy the key. It starts with
   `sk-ant-`.

### 2. Create your `.env` file

In the project folder, create a file named exactly `.env` with these two lines:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
SUFS_SHEET_ID=your-google-sheet-id-here
```

Replace both values with your own. The sheet ID is the long string in your
Google Sheet's URL between `/d/` and `/edit`.

> **Mac:** Open TextEdit, choose **Format → Make Plain Text**, paste the lines,
> and save as `.env` in the project folder. Make sure it doesn't save as
> `.env.txt`.
>
> **Windows:** Open Notepad, paste the lines, then **File → Save As**. Set
> "Save as type" to **All Files**, name it `.env`, and save it in the project
> folder.

`.env.example` lists optional settings you can also add:

- `SUFS_RECEIPTS_DIR`: where receipts are kept, instead of `~/Desktop/SUFS`.
  The app still adds a folder per year inside it, so
  `SUFS_RECEIPTS_DIR=~/Documents/SUFS` uses `~/Documents/SUFS/2026-2027/`.
  Useful on Windows if OneDrive has moved your Desktop.
- `FLASK_SECRET_KEY`: any random string.
- `CDP_PORT`: only if Chrome's debugging port isn't 9222.

### 3. Install dependencies

Open **Terminal** (Mac) or **Command Prompt** (Windows), go to the project
folder, and run these one at a time.

**Mac:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

**Windows:**

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 4. Set up the SUFS Chrome window

The app controls Chrome through its remote-debugging port, which needs a
separate Chrome profile. Signing into your Google account in it brings over
your bookmarks and passwords.

Start it with this command.

**Mac (Terminal):**

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.sufs-agent-chrome"
```

**Windows (Command Prompt):**

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.sufs-agent-chrome"
```

If Chrome is installed somewhere else, change the path to match.

When Chrome opens:

1. Sign into your Google account.
2. Turn on sync (profile photo → **Turn on sync** → **Yes, I'm in**).
3. Sign into the [Step Up for Students portal](https://apply.stepupforstudents.org).
4. Sign into [Amazon](https://www.amazon.com). The Amazon scanner downloads
   invoice PDFs through this window.

Chrome remembers these sign-ins, so you won't need to repeat them.

**Receipts folder.** Receipts live in a folder per scholarship year, by default
`SUFS/<year>/` on your Desktop (for example `~/Desktop/SUFS/2026-2027/`). The
Amazon scanner creates the folder the first time it downloads an invoice. Put
any other receipts (store PDFs, phone photos) there too. To keep them
somewhere else, set `SUFS_RECEIPTS_DIR` in `.env` (step 2).

### 5. Make a shortcut for starting the app

**Mac:** `launch.command` in the project folder does everything: it opens the
SUFS Chrome window, starts the app, and opens the app in a tab. Double-click it
to use it.

For a Desktop icon, make an app from `assets/applet.applescript`: open it in
Script Editor, choose **File → Export**, set **File Format** to
**Application**, and save it to the Desktop as `SUFS Agent`. It expects the
project at `~/Desktop/claude/step_up_tool`; edit the path in the script if
yours is elsewhere.

**Windows:** there's no launcher, so make a shortcut for the Chrome window.
Create `sufs-chrome.bat` (on your Desktop, for example) containing:

```
@echo off
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.sufs-agent-chrome"
```

Double-click it to open the SUFS Chrome window.

### 6. Give the app access to your Google Sheet

The app writes to your tracking sheet as a Google Cloud **service account**.

1. In [Google Cloud Console](https://console.cloud.google.com), create a
   service account in a project with the **Google Sheets API** turned on, and
   download a JSON key for it.
2. Save the key in the project folder as `service_account.json`.
3. Open your tracking sheet, click **Share**, and add the service account's
   email address (the `client_email` in the JSON key) as an **Editor**.
4. Make sure the sheet's ID is in `.env` as `SUFS_SHEET_ID` (step 2).

The app creates the tabs it needs (`Unsubmitted`, `<year> Line Items`,
`Overview`) the first time it uses them.

### 7. Give the app read-only access to Gmail

The Amazon and SUFS status scanners read Gmail through OAuth.

1. In the same Google Cloud project, turn on the **Gmail API**. Under **APIs &
   Services → Credentials**, create an **OAuth client ID** of type **Desktop
   app**, and download its JSON.
2. Save it in the project folder as `gmail_oauth_credentials.json`.
3. With the virtual environment active (step 3), run:

   ```bash
   python authorize_gmail.py
   ```

4. Sign in and allow read-only Gmail access in the browser window that opens.
   The app saves a token to `token.json`.

If Gmail access ever lapses, click **Re-authorize Gmail** on the app's home
page.

---

## Starting the app

**Mac, the easy way:** double-click **SUFS Agent** on the Desktop (or
`launch.command` in the project folder). It opens the SUFS Chrome window if it
isn't open already, starts the app, and opens the app as a tab in that window.
A Terminal window stays open while the app runs. Leave it open; closing it
stops the app.

**By hand (Mac or Windows):**

1. Open the SUFS Chrome window (setup step 4, or `sufs-chrome.bat` on Windows).
2. In Terminal or Command Prompt, go to the project folder and run:

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

3. When it says `Running on http://127.0.0.1:5054`, open
   [http://127.0.0.1:5054](http://127.0.0.1:5054) in any browser. Leave the
   Terminal window open.

> **After updating the app's code, restart it.** Close the Terminal window and
> start the app again. A running copy keeps using the old code.

---

## Submitting a receipt

### Step 1. Open the SUFS form

In the SUFS Chrome window:

1. Go to the Step Up for Students portal.
2. Open your reimbursement request and go to the form where you add line items.
3. Upload the receipt on the SUFS site first. SUFS requires it.

### Step 2. Map the form options (first time only)

Under **System check** on the app's home page, **Form options** shows
**✓ mapped** once the app knows the SUFS dropdown choices (category, type,
description, vendor). If it says **not mapped**, click **Map options** with the
SUFS form open in Chrome. It takes about 30 seconds.

The choices are saved in `form_options.json`, so you don't need to repeat this
for each receipt or session. Run it again only if items stop filling correctly,
which usually means SUFS changed its dropdowns.

### Step 3. Parse the receipt

On the home page, drop the receipt PDF in **Receipt intake** (or click to
choose it), then click **Parse receipt**. Claude reads the receipt and pulls
out each line item.

This page takes PDFs only. For a phone photo, use
[Review receipts folder](#review-receipts-folder), which turns it into a PDF.

If you've logged this exact file before for another child, the app reuses what
it read last time instead of reading it again. See
[Receipts split across children](#receipts-split-across-children).

### Step 4. Check the items

The **Review extracted items** page lists every item. For each one you can:

- **Edit any field** by clicking on it.
- **Uncheck** items you don't want to include.
- Pick the right **category, type, description and vendor** from the
  dropdowns. A field the app wasn't sure about has a **low** or **medium**
  badge; check those first.

> The **Description** dropdown shows broad options like
> "Books/Textbooks/Workbooks", not item names. That's expected; the SUFS form
> uses broad categories.

A banner at the top compares the receipt's printed total with the total of the
items you're submitting.

If this receipt was already submitted for another child, an **Already submitted
for another child** panel appears, and the items already submitted start
unchecked.

### Step 5. Fill the form

Click **Fill form** and switch to the SUFS Chrome window to watch it fill in.
When it finishes, a **Verification — what landed in the form** panel in the app
shows what each field actually holds. Then:

1. **Review everything carefully** in Chrome.
2. Fix anything by hand.
3. **Submit the form yourself.** The app never submits.

### Step 6. Log the submission to your sheet

After SUFS shows its confirmation page with your reimbursement ID:

1. Switch back to the app. A **Log submission to sheet** panel has appeared.
2. Pick the child: one button per child saved on the **Students** page, or
   **Other…** to type a name. A typed name that matches a saved child (in any
   capitalization) is logged with the saved spelling.
3. Enter the **SUFS Reimbursement ID** from the confirmation page.
4. Click **Log to sheet**.

This adds one row per line item to the current scholarship year's tab (for
example `2026-2027 Line Items`, created on the year's first submission), with:

- the item details (description, vendor, price with tax, purchase date, invoice
  file name)
- Status set to `submitted`
- today's date in Date Submitted
- line item IDs like `12345678-1`, `12345678-2`

Each reimbursement ID can be logged only once. The button locks after a
successful log, and the app refuses an ID that's already in any year's tab, so a
double-click can't create duplicate rows.

### Step 7. Clear the purchase out of Unsubmitted

If the purchase is on the **Unsubmitted** tab, the app asks what to do with it
right after logging:

- **Remove from Unsubmitted** deletes that row. Choose this once the purchase
  is fully reimbursed.
- **Keep — more kids to submit** leaves the row and adds
  `partial: <child> <reimbursement id> (MM/DD)` to its Status column. Choose
  this when the same purchase still needs submitting for another child. The
  notes add up, and the prompt shows them next time so you can see who's done.

Nothing is removed automatically. The same purchase is often reimbursed once
per child, so only you know when the last one is done.

**How the receipt is matched to its Unsubmitted row.** The app compares the
uploaded file's name with the row's **Order/Receipt #** column.

- Amazon rows: the scanner fills that column in, and the invoice PDF is named
  to match.
- Rows added by [Review receipts folder](#review-receipts-folder): the column
  holds the file name, so they match too.
- Rows you add by hand: type a reference in the column and name the PDF the
  same, for example `Target 8-14-26` in the column and `Target 8-14-26.pdf` as
  the file.

The match ignores capital letters, spaces at either end, spaces versus
underscores, and the punctuation and accents the upload strips from file names
(`Lowe's 8-1-26.pdf` uploads as `Lowes_8-1-26.pdf`). Otherwise it's exact:
`Target` won't match `Target 8-14-26`. If nothing matches, no prompt appears and
nothing changes.

**Where the receipt file goes.** Once a receipt is finished, its file moves
from this year's folder (`~/Desktop/SUFS/<year>/`) into a `Submitted/`
subfolder, so the year folder only holds receipts still to do. That happens:

- right after logging, if the receipt isn't in Unsubmitted, or
- when you choose **Remove from Unsubmitted**.

**Keep — more kids to submit** leaves the file where it is for the next child.
If you uploaded the file from somewhere else (Downloads, say), nothing moves. If
a move fails, the sheet log still stands.

---

## Review receipts folder

This keeps the **Unsubmitted** tab a complete to-do list. On the home page,
click **Review receipts folder**. The app looks at this year's folder
(`~/Desktop/SUFS/<year>/`, where Amazon invoices also download) and sorts every
receipt into:

- **Untracked:** not submitted and not in Unsubmitted
- **Staged in Unsubmitted**
- **Submitted:** in a Line Items tab
- **Can't process:** a file type it doesn't handle

A receipt is a file *name*, so `IMG_1698.jpeg` and `IMG_1698.pdf` count once.

For untracked receipts, check the ones you want, then click:

- **Add to Unsubmitted** to add them to the to-do list. A photo (`.jpg`,
  `.png`, `.heic`) is first converted to a PDF with the same name (about 480 KB
  instead of 4 MB), and the photo moves to `Originals/`. Claude then reads the
  receipt and fills in the item, store, price and purchase date. If it can't
  read one, the row is added with just the file name for you to fill in.
- **Not submitting** to move the receipt's files to `Not submitting/` so it
  isn't offered again. Drag it back out to undo.

If some receipts in the **Submitted** group are finished (in a Line Items tab
and no longer in Unsubmitted), a **Move N to Submitted/** button files them.
This catches receipts logged before automatic filing existed, or uploaded from
outside the year folder. Receipts still in Unsubmitted have more kids to submit
and stay put.

Nothing is ever deleted. The review skips the `Originals/`, `Not submitting/`
and `Submitted/` subfolders.

---

## Receipts split across children

When one receipt is reimbursed separately for each child, SUFS reviewers need to
see what was already claimed from it. The app helps in two ways.

**A note for the reviewer.** Upload the same receipt for the next child, and
the review page shows an **Already submitted for another child** panel listing
each earlier submission. Click **Download note (PDF)** for a one-page note
naming each earlier submission's child, SUFS student ID, reimbursement ID and
items. Attach it to the new submission along with the receipt.

**Items already submitted start unchecked.** When you log a receipt, the app
saves its items as you confirmed them and which ones went to which child.
Uploading the same file again reuses that saved reading (same items, same order,
no second Claude read), and each item already submitted starts unchecked with a
label like "Submitted for Sam · 12345678". Re-check an item if you really do
mean to include it again.

Both rely on uploading the same file each time:

- The note finds earlier submissions by file name.
- The saved reading is matched by the file's contents, so a renamed copy still
  matches, but an edited or re-exported file is read fresh.

Receipts logged before this feature existed aren't remembered until they're
logged again.

### Students page

Enter each child's SUFS student ID on the **Students** page (home page →
**Students**), using **+ Add child** and **Save**. The IDs are saved only on
this computer. A child with no saved ID shows as "not on file" in the note
until you add one.

**SUFS issues new student IDs every scholarship year.** The page edits the
current year's IDs and keeps earlier years'. After July 1, a **New scholarship
year** banner asks for any IDs not entered yet. The note uses the ID from the
year each earlier submission was made, so a June submission keeps last year's
ID even after the rollover.

---

## SUFS status scanner

After SUFS sends approval, on-hold or payment emails:

1. On the home page, click **SUFS statuses — Line Items**.
2. Click **Scan emails**. The app lists every change it would make.
3. Click **Write update(s) to the sheet** to save them. Nothing is written
   before this.

What it looks for in Gmail:

| Email | Status | Date column |
|---|---|---|
| On hold | `on hold` | Date On Hold |
| Approval | `approved` | Date Approved |
| Payment / remittance | `paid` | Date Paid |

Emails are matched to sheet rows by reimbursement ID and dollar amount, across
every scholarship year's tab, so late payments on last year's rows still land.
It's safe to run again: rows that already have a date are skipped. To replace
existing values, check **Overwrite values that already exist**.

Each scan also rebuilds the **Overview** tab: line items and dollars per child in
each status (Submitted / Approved / Paid / Other), with a "last updated" stamp.

Each email is downloaded and read only once; what it said is saved on this
computer, so later scans only download new emails and finish in seconds. If
Gmail briefly refuses requests ("Quota exceeded" or a dropped connection), the
scan waits and retries.

**From a terminal:** `python scan_testing_status.py` does the same scan and asks
yes/no before writing. Add `--overwrite` to replace existing values.

---

## Amazon order scanner

Needs Gmail and Google Sheets access (setup steps 6 and 7).

1. On the home page, click **Scan Amazon orders**.
2. **Scan from** defaults to your last scan date (or July 1 of the current
   scholarship year the first time). Pick an earlier date to go further back.
3. Click **Scan Gmail**. The app finds Amazon order emails and has Claude check
   each item for SUFS eligibility. This takes 30–60 seconds.
4. Review the results. The badges mean:
   - **Green:** SUFS-eligible
   - **Purple:** already in your tracking sheet
   - **Red:** returned
   - **Yellow:** partly returned (hover to see which item)

   **Show eligible only** hides ineligible and already-logged rows.
5. Check the items you want, then click either:
   - **Log to sheet + download PDFs** to add them to the sheet and download the
     invoice PDFs to this year's folder (`~/Desktop/SUFS/<year>/`) through the
     SUFS Chrome window. PDFs already there are skipped.
   - **Log to sheet only** to add them without downloading PDFs (use this when
     the SUFS Chrome window isn't open).

The next scan starts from today's date automatically.

Orders go to the **Unsubmitted** tab, one row per order. They're purchases you
haven't filed with SUFS yet. When you submit one, logging it (Step 6 of
[Submitting a receipt](#submitting-a-receipt)) adds its line items to the
current year's Line Items tab.

> The scanner never submits anything to SUFS. It only reads Gmail and writes to
> your own sheet.

---

## A new scholarship year

The scholarship year runs **July 1 – June 30**. Each year's submitted line items
get their own tab (`2025-2026 Line Items`, `2026-2027 Line Items`, and so on).
The **Unsubmitted** tab is shared by all years.

After July 1, restart the app, then:

1. **Enter the new student IDs** on the **Students** page. This is the only
   manual step; SUFS issues new IDs every year.

Everything else changes over on its own:

- New submissions log to the new year's tab, which is created on its first
  submission.
- The status scanner and Overview keep reading every year's tab, so late
  approvals and payments from last year still land.
- The Amazon scanner's default start date and the receipts folder
  (`~/Desktop/SUFS/<year>/`) move to the new year.

For developers: every year-specific name and date comes from
`src/scholarship_year.py`, which works out the year from today's date. The one
fixed value is `FIRST_LINE_ITEMS_YEAR` (2025). The older `2024-25` tab uses a
different layout, and the app never reads it.

---

## Purchasing guides

`docs/purchasing_guide_reference.md` is the only guide content the app reads.
It goes into the Claude prompts in `src/receipt_parser.py` (categorizing items)
and `src/amazon_scanner.py` (checking eligibility), so it should stay accurate
and short. Both send it as a cached prompt block, so repeat calls within the
cache window pay a fraction of the price for it.

SUFS updates the guides every year (usually effective July 1, with amendments
later). When they do, rewrite that file from the current sources:

- **FES-UA:** PDF from the Florida Center for Students with Unique Abilities,
  <https://fcsua.org/docs/fesua/2026-27-purchasing-english.pdf>, with a changes
  summary at
  <https://fcsua.org/docs/fesua/2026-27-changes-summary-english.pdf>
- **PEP:** web-only as of 2026-27,
  <https://www.stepupforstudents.org/handbook-web/pep-purchasing-guide/>. The
  old `go.stepupforstudents.org/hubfs/GUIDES/PEP-Purchasing-Guide.pdf` link
  still works but serves the outdated 2025-26 file, so don't use it.

Copies of the sources are kept in `docs/sources/` (git-ignored, since all PDFs
are), with last year's under `docs/sources/archive-2025-26/`.

After rewriting, check the category names in the guide against
`form_options.json`. `src/option_match.py` snaps the parser's labels to real
dropdown values, and a category that matches nothing leaves the form field
blank without any warning.

---

## Your data stays on this computer

The repo is public, so everything personal lives in local files that git
ignores:

| File | Holds |
|---|---|
| `.env` | Anthropic API key, sheet ID |
| `service_account.json` | Google Sheets credentials |
| `gmail_oauth_credentials.json`, `token.json` | Gmail credentials |
| `students.json` | each child's SUFS student ID, per scholarship year |
| `receipt_history.json` | which receipt items went to which child |
| `email_scan_cache.json` | what each SUFS status email said |

`email_scan_cache.json` is always safe to delete; the next status scan just
reads every email again. It also resets itself when the email-reading code
changes.

Uploaded receipts are deleted from the app's temp folder as soon as they're
read. `test_repo_privacy.py` fails if a real-looking Amazon order number or a
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

Each file prints a line starting `OK —` when everything passes.

---

## Troubleshooting

**Changes don't show up after an update**
Restart the app: close the Terminal window running it, then start it again.

**"Failed to connect to Chrome"**
The SUFS Chrome window isn't open, or it was opened without
`--remote-debugging-port=9222`. Ordinary Chrome windows won't work. Start it
with the launcher or the command in setup step 4.

**"No SUFS tab found"**
Open the reimbursement form as a tab in the SUFS Chrome window before clicking
**Fill form**.

**Items aren't filling correctly**
Click **Map options** on the home page with the SUFS form open, then try again.
This re-reads the dropdown choices and usually fixes it.

**"Gmail not authorized"**
Click **Re-authorize Gmail** on the home page, or run
`python authorize_gmail.py`. If the home page says **no client secrets**,
`gmail_oauth_credentials.json` is missing (setup step 7).

**Gmail "Quota exceeded … Units per minute per user" (403)**
Gmail briefly refuses requests that come too fast. The scanners wait and retry
on their own, so this should be rare. If it still happens, wait a minute and
scan again.

**The app won't start**
Activate the virtual environment first: `source .venv/bin/activate` (Mac) or
`.venv\Scripts\activate` (Windows).

**"python" not found (Mac)**
Use `python3` instead of `python`.

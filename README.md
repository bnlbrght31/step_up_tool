# SUFS Reimbursement Agent

This tool reads a receipt PDF and automatically fills out your Step Up for Students reimbursement form in Chrome. You review everything — it never submits.

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
```

Replace `sk-ant-your-key-here` with your actual key.

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

Open a **second** Terminal (Mac) or Command Prompt (Windows) window, navigate to the project folder, and run:

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

You should see something like `Running on http://127.0.0.1:5050`. Leave this window open.

### Step 4 — Open the app in your browser

Go to [http://127.0.0.1:5050](http://127.0.0.1:5050) in any browser (your regular Chrome is fine).

### Step 5 — Discover form options (first time per reimbursement session)

On the app's home page, click **Discover** with the SUFS form open in your SUFS Chrome window. This takes about 30 seconds and teaches the agent all the available dropdown options (category, type, description, vendor). You'll see a green "✓ Discovered" badge when it's done.

> You only need to do this once per session — not every receipt.

### Step 6 — Upload your receipt

Click **"Click to select a receipt PDF"**, choose your receipt, then click **Parse Receipt**. The agent will read the receipt and extract each line item.

### Step 7 — Review the extracted items

You'll see a list of items pulled from the receipt. For each one you can:
- **Edit any field** by clicking on it
- **Uncheck** items you don't want to include
- Choose the correct **category, type, description, and vendor** from the dropdowns

> The **Description** dropdown shows generic options (like "Books/Textbooks/Workbooks") — this is correct. The SUFS form uses broad categories, not individual item names.

### Step 8 — Fill the form

Click **Fill Form**. Switch to your SUFS Chrome window and watch it fill in the fields. When it's done:

1. **Review everything carefully** in Chrome
2. Make any corrections by hand
3. **Submit the form yourself** — the agent never submits

---

## Troubleshooting

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

# Code Review & Enhancement Ideas — step_up_tool (2026-06-14)

_Findings log; no code was changed. Scope: `main.py`, `src/` (receipt_parser, browser_agent, amazon_scanner, sufs_email_scanner, reimbursement_scraper, sheets_logger, models, pdf_downloader)._

## What it does
Flask app that parses a Step Up For Students receipt PDF with Claude, lets the user confirm line items, then drives the user's **own** Chrome (via CDP) to fill the SUFS reimbursement form. Also scans Amazon order emails and reconciles reimbursement status from SUFS emails into Google Sheets.

## ✅ Good — safety constraint respected
The hard rule "**NEVER SUBMIT THE FORM**" is honored: `fill_form` connects to the user's existing browser, fills fields, and ends with `page.bring_to_front()` for manual review (`browser_agent.py:437-446`) — no submit selector is ever clicked. Models are all current (`claude-sonnet-4-6`, `claude-haiku-4-5-20251001`), and `CLAUDE.md` is correctly gitignored per the spec.

---

## Bugs / correctness

1. **Tax math is delegated to the LLM. [HIGH for a money tool]**
   The extraction prompt asks Claude to *"distribute [total tax] proportionally across items… Round to 2 decimal places"* (`receipt_parser.py:40`). LLMs are unreliable at arithmetic, so per-item tax can be wrong and **won't necessarily sum to the receipt's actual tax/total** — which directly affects reimbursement amounts. Extract per-item costs + the receipt's total tax, then distribute and round **in Python**, and reconcile the computed grand total against the receipt total before filling.

2. **Receipt line items are stored in a client-side cookie session. [MEDIUM]**
   `session["items"] = [...]` (`main.py:51`) with Flask's default **signed-cookie** session (no server-side store configured). A long/multi-item receipt easily exceeds the ~4KB cookie limit, after which the cookie is dropped and `/confirm` silently bounces back to `/` with no error (`main.py:59-61`). Use a server-side session (Flask-Session filesystem — the sibling `nfl_pickem_app` already does this) or stash items in `/tmp` keyed by an id.

3. **No reconciliation between parsed values and the form's real dropdown options. [MEDIUM]**
   `discover_form_options` captures the actual `category/type/description/vendor` choices into `form_options.json`, but the parser emits free-text labels from the purchasing guide, and `_fill_item` feeds them straight to `_bs_select` (`browser_agent.py:369-403`). If a label doesn't exactly match a dropdown option, the select silently picks nothing and the field is left blank — easy to miss before manual submit. Snap parsed labels to the nearest valid option and surface any mismatch on the confirm page.

4. **`parse_receipt` return type annotation is wrong.** Declared `-> list[LineItem]` (`receipt_parser.py:65`) but returns a tuple `(items, parse_cost)` (`:111`). The current caller unpacks correctly (`main.py:47`), but the annotation will mislead the next caller. (Also `parse_cost` is computed manually at `:92` and again inside `_print_cost` — collapse to one.)

---

## Sub-optimal setup

5. **Debug server + default secret.** `app.run(debug=True, port=5050)` (`main.py:188`) with `secret_key` defaulting to `"dev-secret-change-in-prod"` (`main.py:20`). Because this app drives the user's real logged-in browser via CDP, the Werkzeug debugger is a sharper risk than usual — bind to `127.0.0.1`, turn debug off by default, and require a real secret.

6. **Uploaded receipts linger in `/tmp/sufs_uploads`.** `upload()` saves the PDF (`main.py:42-44`) and never deletes it. Receipts contain personal purchase data — clean up after parsing (or process in-memory).

7. **No regression guard on the "never submit" invariant.** It's respected today, but a future edit to the intricate Blazor field-targeting in `_fill_item` could add an stray click. A tiny test asserting no submit-like selector is ever invoked would lock in the most important safety property.

---

## Enhancement ideas

- **Python-side tax/total reconciliation** (fixes #1): show "extracted total vs. receipt total" on the confirm page and block/flag if they diverge beyond a cent or two.
- **Option snapping with confidence** (fixes #3): fuzzy-match parsed category/type to the discovered options, and badge low-confidence matches in the confirm UI for a quick human check.
- **Post-fill verification:** screenshot or read back each filled row so the user sees exactly what was entered before they submit manually.
- **Finish the Sheets logging loop:** `sheets_logger.py` + `reimbursement_scraper.py` already reconcile status — wire submission logging into the confirm flow so every filled request is recorded automatically (the planned future enhancement).
- **Form-targeting test harness:** save a static copy of the SUFS form and run `_fill_item` against it in CI — the multi-step Blazor DOM logic (category→type→description insertion) is the most fragile code here.
- **Auto-clean uploads** and add a simple audit log of what was parsed/filled per receipt.

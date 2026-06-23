import asyncio
import json
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

load_dotenv()

from src.amazon_scanner import load_last_scan, save_last_scan, scan_amazon_orders
from src.browser_agent import discover_form_options, fill_form, inspect_form_elements, load_form_options
from src.gmail_auth import reauthorize as gmail_reauthorize, token_status as gmail_token_status
from src.models import LineItem
from src.option_match import build_matches
from src.pdf_downloader import download_invoices
from src.receipt_parser import parse_receipt
from src.sheets_logger import append_orders, get_existing_order_numbers, log_submission_to_testing

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

UPLOAD_DIR = Path("/tmp/sufs_uploads")
ALLOWED_EXTENSIONS = {"pdf"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    form_options = load_form_options()
    return render_template("index.html", options_discovered=form_options is not None)


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("receipt")
    if not file or file.filename == "" or not allowed_file(file.filename):
        return redirect(url_for("index"))

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filepath = UPLOAD_DIR / secure_filename(file.filename)
    file.save(filepath)

    try:
        items, parse_cost, reconciliation = parse_receipt(str(filepath))
    except Exception as e:
        return render_template("index.html", error=f"Failed to parse receipt: {e}", options_discovered=load_form_options() is not None)
    finally:
        # Receipts hold personal purchase data — don't leave them on disk.
        filepath.unlink(missing_ok=True)

    session["items"] = [item.to_dict() for item in items]
    session["parse_cost"] = parse_cost
    session["reconciliation"] = reconciliation
    session["invoice_filename"] = secure_filename(file.filename)
    return redirect(url_for("confirm"))


@app.route("/confirm")
def confirm():
    items = session.get("items", [])
    if not items:
        return redirect(url_for("index"))
    form_options = load_form_options()
    parse_cost = session.get("parse_cost")
    matches = build_matches(items, form_options)
    reconciliation = session.get("reconciliation")
    return render_template(
        "confirm.html",
        items=items,
        matches=matches,
        reconciliation=reconciliation,
        form_options_json=json.dumps(form_options) if form_options else "null",
        parse_cost=f"${parse_cost:.4f}" if parse_cost else None,
        enumerate=enumerate,
    )


@app.route("/inspect", methods=["POST"])
def inspect():
    cdp_port = int(os.environ.get("CDP_PORT", 9222))
    try:
        elements = asyncio.run(inspect_form_elements(cdp_port=cdp_port))
        return jsonify({"success": True, "elements": elements})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/discover", methods=["POST"])
def discover():
    data = request.get_json() or {}
    form_url = data.get("form_url", "").strip()
    cdp_port = int(os.environ.get("CDP_PORT", 9222))

    try:
        options = asyncio.run(discover_form_options(form_url=form_url, cdp_port=cdp_port))
        return jsonify({"success": True, "options": options})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/fill", methods=["POST"])
def fill():
    data = request.get_json()
    form_url = data.get("form_url", "").strip()
    items_data: list[dict] = data.get("items", [])

    selected = [LineItem.from_dict(i) for i in items_data if i.get("include")]
    if not selected:
        return jsonify({"error": "No items selected."}), 400

    cdp_port = int(os.environ.get("CDP_PORT", 9222))

    try:
        readback = asyncio.run(fill_form(form_url=form_url, items=selected, cdp_port=cdp_port))
        return jsonify({"success": True, "filled": len(selected), "readback": readback})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/log-submission", methods=["POST"])
def log_submission():
    data = request.get_json() or {}
    student = data.get("student", "").strip()
    sufs_id = data.get("sufs_id", "").strip()
    items   = [i for i in data.get("items", []) if i.get("include")]

    if not student or not sufs_id:
        return jsonify({"error": "Student name and SUFS ID are required."}), 400
    if not items:
        return jsonify({"error": "No selected items to log."}), 400

    invoice_filename = session.get("invoice_filename", "")
    try:
        log_submission_to_testing(student, sufs_id, items, invoice_filename)
        return jsonify({"success": True, "logged": len(items)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/gmail/status")
def gmail_status():
    """Report whether the Gmail token is authorized / expired / missing."""
    return jsonify(gmail_token_status())


@app.route("/gmail/auth", methods=["POST"])
def gmail_auth():
    """
    Run the interactive Gmail OAuth flow. This opens a browser tab for the
    Google consent screen and blocks until you finish (or it times out).
    """
    try:
        email = gmail_reauthorize(timeout_seconds=300)
        return jsonify({"success": True, "email": email})
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Authorization did not complete: {e}"}), 500


@app.route("/sufs-scan/<tab>")
def sufs_scan(tab):
    from src.status_scan import TAB_META
    if tab not in TAB_META:
        return redirect(url_for("index"))
    return render_template("sufs_status.html", tab=tab, meta=TAB_META[tab])


def _refresh_overview_safe():
    """Rebuild the Overview dashboard + stamp 'last email scan'. Never fatal to a scan."""
    try:
        from src.overview import refresh_overview
        refresh_overview()
    except Exception as e:
        print(f"[overview] refresh skipped: {e}")


@app.route("/sufs-scan/<tab>/preview", methods=["POST"])
def sufs_scan_preview(tab):
    from src.status_scan import PREVIEW
    if tab not in PREVIEW:
        return jsonify({"error": "Unknown tab."}), 400
    overwrite = bool((request.get_json() or {}).get("overwrite"))
    try:
        result = PREVIEW[tab](overwrite=overwrite)
        _refresh_overview_safe()  # you just ran the scanner — refresh + timestamp
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"{e}  (if this is an auth error, re-authorize Gmail on the home page)"}), 500


@app.route("/sufs-scan/<tab>/apply", methods=["POST"])
def sufs_scan_apply(tab):
    from src.status_scan import APPLY
    if tab not in APPLY:
        return jsonify({"error": "Unknown tab."}), 400
    updates = (request.get_json() or {}).get("updates", [])
    if not updates:
        return jsonify({"error": "No updates to write."}), 400
    try:
        written = APPLY[tab](updates)
        _refresh_overview_safe()  # data changed — rebuild the dashboard
        return jsonify({"success": True, "written": written})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/scan")
def scan():
    return render_template("scan.html")


@app.route("/scan/state")
def scan_state():
    return jsonify({"last_scan_date": load_last_scan()})


@app.route("/scan/run", methods=["POST"])
def scan_run():
    data = request.get_json() or {}
    from_date = data.get("from_date")  # YYYY-MM-DD from date picker, or None
    try:
        existing = get_existing_order_numbers()
        orders, after_date, scan_cost = scan_amazon_orders(existing, from_date=from_date)
        return jsonify({"orders": orders, "after_date": after_date, "scan_cost": round(scan_cost, 4)})
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/scan/log", methods=["POST"])
def scan_log():
    data = request.get_json() or {}
    orders = data.get("orders", [])
    if not orders:
        return jsonify({"error": "No orders provided."}), 400
    try:
        append_orders(orders)
        save_last_scan()
        return jsonify({"success": True, "logged": len(orders)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/scan/pdfs", methods=["POST"])
def scan_pdfs():
    data = request.get_json() or {}
    order_ids = data.get("order_ids", [])
    if not order_ids:
        return jsonify({"error": "No order IDs provided."}), 400
    cdp_port = int(os.environ.get("CDP_PORT", 9222))
    try:
        results = download_invoices(order_ids, cdp_port=cdp_port)
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _app_port(default=5054):
    """Resolve the HTTP port from the shared registry ($PORT still wins)."""
    import sys
    for parent in Path(__file__).resolve().parents:
        if (parent / "shared" / "ports.py").exists():
            sys.path.insert(0, str(parent / "shared"))
            try:
                from ports import get_port
                return get_port("step_up_tool", default=default)
            except Exception:
                break
    return int(os.environ.get("PORT", default))


if __name__ == "__main__":
    # Bind localhost only and keep debug off unless FLASK_DEBUG is set (this app
    # drives the user's real logged-in browser via CDP, so the Werkzeug debugger
    # is a sharper risk than usual). Threaded so a blocking OAuth flow
    # (/gmail/auth) doesn't freeze the UI.
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="127.0.0.1", port=_app_port(), debug=debug, threaded=True)

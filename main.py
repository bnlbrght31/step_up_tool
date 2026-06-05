import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

load_dotenv()

from src.amazon_scanner import load_last_scan, save_last_scan, scan_amazon_orders
from src.browser_agent import discover_form_options, fill_form, inspect_form_elements, load_form_options
from src.models import LineItem
from src.pdf_downloader import download_invoices
from src.receipt_parser import parse_receipt
from src.sheets_logger import append_orders, get_existing_order_numbers

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-in-prod")

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
        items = parse_receipt(str(filepath))
    except Exception as e:
        return render_template("index.html", error=f"Failed to parse receipt: {e}", options_discovered=load_form_options() is not None)

    session["items"] = [item.to_dict() for item in items]
    return redirect(url_for("confirm"))


@app.route("/confirm")
def confirm():
    items = session.get("items", [])
    if not items:
        return redirect(url_for("index"))
    form_options = load_form_options()
    return render_template(
        "confirm.html",
        items=items,
        form_options_json=json.dumps(form_options) if form_options else "null",
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
        asyncio.run(fill_form(form_url=form_url, items=selected, cdp_port=cdp_port))
        return jsonify({"success": True, "filled": len(selected)})
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
        orders, after_date = scan_amazon_orders(existing, from_date=from_date)
        return jsonify({"orders": orders, "after_date": after_date})
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


if __name__ == "__main__":
    app.run(debug=True, port=5050)

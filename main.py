import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

load_dotenv()

from src.browser_agent import fill_form
from src.models import LineItem
from src.receipt_parser import parse_receipt

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-in-prod")

UPLOAD_DIR = Path("/tmp/sufs_uploads")
ALLOWED_EXTENSIONS = {"pdf"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    return render_template("index.html")


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
        return render_template("index.html", error=f"Failed to parse receipt: {e}")

    session["items"] = [item.to_dict() for item in items]
    return redirect(url_for("confirm"))


@app.route("/confirm")
def confirm():
    items = session.get("items", [])
    if not items:
        return redirect(url_for("index"))
    return render_template("confirm.html", items=items, enumerate=enumerate)


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


if __name__ == "__main__":
    app.run(debug=True, port=5000)

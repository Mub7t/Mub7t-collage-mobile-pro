"""
RL Maintenance Report Generator — app.py  v5
"""

import os
import re
import json
import uuid
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, send_file, flash, jsonify
)
from werkzeug.utils import secure_filename

from services.ocr_service            import extract_text_from_image
from services.parser_service         import parse_email_text
from services.photo_combiner_service import combine_photos

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "rl-report-secret-key-2026")

UPLOAD_FOLDER  = os.path.join(os.path.dirname(__file__), "uploads")
IMAGES_FOLDER  = os.path.join(os.path.dirname(__file__), "generated_images")
ALLOWED_EXTENSIONS     = {"png", "jpg", "jpeg"}
MAX_CONTENT_LENGTH     = 100 * 1024 * 1024   # 100 MB for many photos
MAX_PHOTOS             = 30

app.config["UPLOAD_FOLDER"]      = UPLOAD_FOLDER
app.config["IMAGES_FOLDER"]      = IMAGES_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(IMAGES_FOLDER, exist_ok=True)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def today_formatted() -> str:
    try:
        return datetime.now().strftime("%B %-d, %Y")
    except ValueError:
        return datetime.now().strftime("%B %d, %Y")


def _empty_task() -> dict:
    return {
        "row_num": 1, "task": "Field Service",
        "site_id": "", "approach": "N/A",
        "problem": "", "vendor": "N/A",
        "sap_notification": "", "action_taken": "",
        "current_status": "Solved",
        "comments": "Waiting for RM confirmation",
    }


# ══════════════════════════════════════════════════════════════════════════════
# SERVICE 1 — PREPARE REPORT
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload")
def upload():
    return render_template("upload.html")


@app.route("/extract", methods=["POST"])
def extract():
    """OCR path: upload image → parse → review."""
    if "image" not in request.files or request.files["image"].filename == "":
        flash("No file selected. Please choose an image or use Manual mode.", "error")
        return redirect(url_for("upload"))

    file = request.files["image"]
    if not allowed_file(file.filename):
        flash("Unsupported file type. Please upload PNG, JPG, or JPEG.", "error")
        return redirect(url_for("upload"))

    ext       = file.filename.rsplit(".", 1)[1].lower()
    safe_name = f"{uuid.uuid4().hex}.{ext}"
    filepath  = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
    file.save(filepath)

    ocr_error = None
    raw_text  = ""
    try:
        raw_text = extract_text_from_image(filepath)
    except Exception as exc:
        ocr_error = str(exc)

    parsed = {}
    if raw_text:
        try:
            parsed = parse_email_text(raw_text)
        except Exception as exc:
            ocr_error = (ocr_error or "") + f" Parsing error: {exc}"

    supervisor = parsed.get("supervisor", "")
    team       = parsed.get("team", "")
    tasks      = parsed.get("tasks", [])

    # If nothing was extracted, start with one blank row so the user
    # doesn't face an empty table with no way to see what happened
    if not tasks:
        tasks = [_empty_task()]

    return render_template(
        "review.html",
        supervisor=supervisor,
        team=team,
        shift="Overnight",
        time_range="12 AM - 8 AM",
        date=today_formatted(),
        tasks=tasks,
        tasks_json=json.dumps(tasks),
        ocr_error=ocr_error,
        raw_text=raw_text,
        manual_mode=False,
    )


@app.route("/manual-report")
def manual_report():
    """Manual path: go straight to review page with one blank row."""
    tasks = [_empty_task()]
    return render_template(
        "review.html",
        supervisor="",
        team="",
        shift="Overnight",
        time_range="12 AM - 8 AM",
        date=today_formatted(),
        tasks=tasks,
        tasks_json=json.dumps(tasks),
        ocr_error=None,
        raw_text="",
        manual_mode=True,
    )


@app.route("/report-preview", methods=["POST"])
def report_preview():
    supervisor = request.form.get("supervisor", "").strip()
    team       = request.form.get("team", "").strip()
    shift      = request.form.get("shift", "Overnight").strip()
    time_range = request.form.get("time_range", "12 AM - 8 AM").strip()
    date       = request.form.get("date", today_formatted()).strip()
    tasks_json = request.form.get("tasks_json", "[]")

    try:
        tasks = json.loads(tasks_json)
    except json.JSONDecodeError:
        flash("Could not read task data. Please try again.", "error")
        return redirect(url_for("upload"))

    errors = []
    if not supervisor:
        errors.append("Supervisor Name is required.")
    if not team:
        errors.append("Team / Technicians is required.")
    for i, task in enumerate(tasks, start=1):
        if not task.get("site_id", "").strip():
            errors.append(f"Row {i}: Site ID is required.")
        if not task.get("problem", "").strip():
            errors.append(f"Row {i}: Problem is required.")
        if not task.get("action_taken", "").strip():
            errors.append(f"Row {i}: Action Taken is required.")

    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    return render_template(
        "report_preview.html",
        supervisor=supervisor,
        team=team,
        shift=shift,
        time_range=time_range,
        date=date,
        tasks=tasks,
        tasks_json=tasks_json,
    )


@app.route("/api/extract", methods=["POST"])
def api_extract():
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400
    file = request.files["image"]
    if not allowed_file(file.filename):
        return jsonify({"error": "Unsupported file type"}), 400
    ext  = file.filename.rsplit(".", 1)[1].lower()
    path = os.path.join(app.config["UPLOAD_FOLDER"], f"{uuid.uuid4().hex}.{ext}")
    file.save(path)
    try:
        raw_text = extract_text_from_image(path)
        parsed   = parse_email_text(raw_text)
        return jsonify({"success": True, "data": parsed, "raw_text": raw_text})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# SERVICE 2 — COMBINE PHOTOS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/combine-photos")
def combine_photos_page():
    return render_template("combine_photos.html")


@app.route("/combine-photos/preview", methods=["POST"])
def combine_photos_preview():
    # Collect all uploaded files from the 'photos' field
    all_files = request.files.getlist("photos")
    # Filter out empty slots (browser may send empty file objects)
    files = [f for f in all_files if f and f.filename and f.filename.strip()]

    if not files:
        flash("Please upload at least one photo.", "error")
        return redirect(url_for("combine_photos_page"))

    if len(files) > MAX_PHOTOS:
        flash(f"You can upload a maximum of {MAX_PHOTOS} photos. You sent {len(files)}.", "error")
        return redirect(url_for("combine_photos_page"))

    invalid = [f.filename for f in files if not allowed_file(f.filename)]
    if invalid:
        flash(f"Unsupported file type(s): {', '.join(invalid)}. Please use PNG, JPG, or JPEG.", "error")
        return redirect(url_for("combine_photos_page"))

    site_name         = request.form.get("site_name", "").strip()
    watermark_text    = request.form.get("watermark_text", "").strip()
    watermark_opacity = max(5, min(40, int(request.form.get("watermark_opacity", 15) or 15)))
    watermark_size    = request.form.get("watermark_size", "medium").lower()
    if watermark_size not in ("small", "medium", "large"):
        watermark_size = "medium"

    saved_paths = []
    for f in files:
        ext  = f.filename.rsplit(".", 1)[1].lower()
        path = os.path.join(app.config["UPLOAD_FOLDER"], f"{uuid.uuid4().hex}.{ext}")
        f.save(path)
        saved_paths.append(path)

    try:
        jpeg_bytes, file_size = combine_photos(
            image_paths=saved_paths,
            site_name=site_name,
            watermark_text=watermark_text,
            watermark_opacity=watermark_opacity,
            watermark_size=watermark_size,
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("combine_photos_page"))
    except Exception as exc:
        flash(f"Image generation failed: {exc}", "error")
        return redirect(url_for("combine_photos_page"))

    date_slug = datetime.now().strftime("%Y-%m-%d")
    safe_site = re.sub(r"[^A-Za-z0-9_\-]", "_", site_name) if site_name else ""
    filename  = (f"combined_photos_{safe_site}_{date_slug}.jpg"
                 if safe_site else f"combined_photos_{date_slug}.jpg")
    out_path  = os.path.join(app.config["IMAGES_FOLDER"], filename)
    with open(out_path, "wb") as fh:
        fh.write(jpeg_bytes)

    size_str = (f"{file_size/(1024*1024):.2f} MB"
                if file_size >= 1024*1024 else f"{file_size/1024:.1f} KB")

    return render_template(
        "combine_preview.html",
        filename=filename,
        file_size=size_str,
        site_name=site_name,
        photo_count=len(saved_paths),
    )


@app.route("/combine-photos/download/<filename>")
def combine_photos_download(filename: str):
    safe = os.path.basename(filename)
    path = os.path.join(app.config["IMAGES_FOLDER"], safe)
    if not os.path.isfile(path):
        flash("File not found. Please generate the image again.", "error")
        return redirect(url_for("combine_photos_page"))
    return send_file(path, as_attachment=True, download_name=safe, mimetype="image/jpeg")


@app.route("/combine-photos/preview-image/<filename>")
def combine_photos_preview_image(filename: str):
    safe = os.path.basename(filename)
    path = os.path.join(app.config["IMAGES_FOLDER"], safe)
    if not os.path.isfile(path):
        return "", 404
    return send_file(path, mimetype="image/jpeg")


@app.errorhandler(413)
def too_large(_):
    flash("Total file size too large. Maximum is 100 MB.", "error")
    return redirect(url_for("upload"))


@app.route("/preventive-table")
def preventive_table():
    return render_template("preventive_table.html")


if __name__ == "__main__":
    app.run(debug=True)
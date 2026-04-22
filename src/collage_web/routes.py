from __future__ import annotations
from pathlib import Path
from flask import Blueprint, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename
from .builder import build_collage
from .config import ALLOWED_EXTENSIONS, OUTPUT_DIR, UPLOAD_DIR
from .forms import CollageOptions
from .utils import allowed_file, unique_name

bp = Blueprint("main", __name__)

@bp.get("/")
def index():
    return render_template("index.html")

@bp.post("/create")
def create():
    files = request.files.getlist("images")
    if not files:
        return render_template("index.html", error="Please select one or more images.")

    saved_paths: list[Path] = []
    for file in files:
        if not file or not file.filename:
            continue
        if not allowed_file(file.filename, ALLOWED_EXTENSIONS):
            continue
        safe = secure_filename(file.filename)
        ext = Path(safe).suffix.lower() or ".jpg"
        name = unique_name("upload", ext)
        path = UPLOAD_DIR / name
        file.save(path)
        saved_paths.append(path)

    if not saved_paths:
        return render_template("index.html", error="No supported image files were uploaded.")

    try:
        options = CollageOptions(
            title=request.form.get("title", "").strip(),
            font_size=int(request.form.get("font_size", 40)),
            align=request.form.get("align", "center"),
            max_size_mb=float(request.form.get("max_size_mb", 8)),
            cell_size=int(request.form.get("cell_size", 420)),
            padding=int(request.form.get("padding", 14)),
        )
        output_name = unique_name("collage", ".jpg")
        output_path = OUTPUT_DIR / output_name
        build_collage(saved_paths, output_path, options)
        size_mb = output_path.stat().st_size / (1024 * 1024)
        return render_template(
            "index.html",
            success=True,
            download_url=url_for("main.download", filename=output_name),
            preview_url=url_for("main.preview", filename=output_name),
            final_size=f"{size_mb:.2f}",
            image_count=len(saved_paths),
        )
    except Exception as exc:
        return render_template("index.html", error=str(exc))

@bp.get("/download/<filename>")
def download(filename: str):
    path = OUTPUT_DIR / secure_filename(filename)
    if not path.exists():
        return "File not found.", 404
    return send_file(path, as_attachment=True, download_name=path.name)

@bp.get("/preview/<filename>")
def preview(filename: str):
    path = OUTPUT_DIR / secure_filename(filename)
    if not path.exists():
        return "File not found.", 404
    return send_file(path, mimetype="image/jpeg")

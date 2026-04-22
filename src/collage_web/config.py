from __future__ import annotations
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

MAX_CONTENT_LENGTH = 200 * 1024 * 1024
SECRET_KEY = "change-this-in-production"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

for path in (UPLOAD_DIR, OUTPUT_DIR):
    path.mkdir(parents=True, exist_ok=True)

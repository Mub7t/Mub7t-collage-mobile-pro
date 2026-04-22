from __future__ import annotations
import math
import uuid
from pathlib import Path
from PIL import Image

def allowed_file(filename: str, allowed_extensions: set[str]) -> bool:
    return Path(filename).suffix.lower() in allowed_extensions

def unique_name(prefix: str, suffix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}{suffix}"

def calculate_grid(item_count: int) -> tuple[int, int]:
    if item_count <= 0:
        raise ValueError("item_count must be > 0")
    cols = math.ceil(math.sqrt(item_count))
    rows = math.ceil(item_count / cols)
    return cols, rows

def contain_image(img: Image.Image, max_width: int, max_height: int) -> Image.Image:
    copy = img.convert("RGB")
    copy.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return copy

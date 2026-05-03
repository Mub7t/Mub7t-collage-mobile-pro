"""
photo_combiner_service.py
────────────────────────
Memory-safe photo combiner for RL Maintenance Services.

Main goal:
- Accept original high-resolution uploaded photos.
- Process one photo at a time.
- Resize each photo directly into its final cell.
- Paste it into the final canvas.
- Close the original image immediately.
- Compress final JPG to <= 2 MB.

This avoids keeping all original phone photos open in RAM, so it is much more
stable on Render when combining 20–25 photos.
"""

from __future__ import annotations

import io
import math
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps


# ── Layout constants ───────────────────────────────────────────────────────────
CANVAS_WIDTH = 1800
OUTER_PADDING = 60
CELL_GAP = 18
CELL_ASPECT = 0.72       # fixed landscape-biased cell; clean report sheet look
BG_COLOR = (255, 255, 255)
CELL_BORDER = (232, 232, 232)

HEADER_HEIGHT = 100
HEADER_FG = (20, 20, 20)

MAX_FILE_BYTES = 2 * 1024 * 1024
QUALITY_STEPS = [92, 88, 83, 78, 72, 65, 58, 52, 46]
DIMENSION_SCALES = [0.92, 0.84, 0.76, 0.68, 0.60, 0.52]

WATERMARK_SIZES = {"small": 36, "medium": 58, "large": 86}
DEFAULT_WM_SIZE = "medium"
DEFAULT_WM_OPACITY = 15


def combine_photos(
    image_paths: List[str],
    site_name: str = "",
    watermark_text: str = "",
    watermark_opacity: int = DEFAULT_WM_OPACITY,
    watermark_size: str = DEFAULT_WM_SIZE,
    canvas_width: int = CANVAS_WIDTH,
) -> Tuple[bytes, int]:
    """
    Build a combined image from uploaded photos.

    Important:
    This function intentionally does NOT load all images into memory.
    It opens, resizes, pastes, and closes each image one by one.
    """
    if not image_paths:
        raise ValueError("No images provided.")

    count = len(image_paths)
    cols = _choose_cols(count)
    rows = math.ceil(count / cols)

    pad = OUTER_PADDING
    gap = CELL_GAP

    cell_w = (canvas_width - 2 * pad - gap * (cols - 1)) // cols
    cell_h = round(cell_w * CELL_ASPECT)

    has_header = bool(site_name and site_name.strip())
    header_h = HEADER_HEIGHT if has_header else 0

    canvas_h = header_h + pad + rows * cell_h + max(0, rows - 1) * gap + pad

    canvas = Image.new("RGB", (canvas_width, canvas_h), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    if has_header:
        _draw_header(draw, site_name.strip(), canvas_width, header_h)

    y0 = header_h + pad

    for idx, path in enumerate(image_paths):
        row = idx // cols
        col = idx % cols

        x = pad + col * (cell_w + gap)
        y = y0 + row * (cell_h + gap)

        _paste_path_in_cell(canvas, path, x, y, cell_w, cell_h)

    if watermark_text and watermark_text.strip():
        opacity = max(5, min(40, int(watermark_opacity or DEFAULT_WM_OPACITY)))
        size_key = (watermark_size or DEFAULT_WM_SIZE).lower()
        if size_key not in WATERMARK_SIZES:
            size_key = DEFAULT_WM_SIZE

        canvas = _apply_watermark(canvas, watermark_text.strip(), opacity, size_key)

    data = _compress(canvas, canvas_width)
    canvas.close()
    return data, len(data)


def _choose_cols(n: int) -> int:
    """
    Keep the sheet readable:
    - 1 photo  = 1 column
    - 2 photos = 2 columns
    - 3 photos = 3 columns
    - 4+       = 4 columns
    """
    if n <= 1:
        return 1
    if n == 2:
        return 2
    if n == 3:
        return 3
    return 4


def _paste_path_in_cell(
    canvas: Image.Image,
    path: str,
    x: int,
    y: int,
    cell_w: int,
    cell_h: int,
) -> None:
    """
    Open one image, fix orientation, resize it to fit the cell,
    paste it, then close it immediately.
    """
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([x, y, x + cell_w, y + cell_h], outline=CELL_BORDER, fill=BG_COLOR)

    img = Image.open(path)
    try:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")

        iw, ih = img.size
        scale = min(cell_w / iw, cell_h / ih)
        new_w = max(1, round(iw * scale))
        new_h = max(1, round(ih * scale))

        resized = img.resize((new_w, new_h), Image.LANCZOS)

        paste_x = x + (cell_w - new_w) // 2
        paste_y = y + (cell_h - new_h) // 2
        canvas.paste(resized, (paste_x, paste_y))

        resized.close()
    finally:
        img.close()


def _draw_header(
    draw: ImageDraw.ImageDraw,
    text: str,
    canvas_width: int,
    header_h: int,
) -> None:
    font_size = max(32, header_h // 2)
    font = _load_font(font_size, bold=True)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    tx = (canvas_width - tw) // 2
    ty = (header_h - th) // 2

    draw.text((tx, ty), text, fill=HEADER_FG, font=font)


def _apply_watermark(
    canvas: Image.Image,
    text: str,
    opacity_pct: int,
    size_label: str,
) -> Image.Image:
    font_size = WATERMARK_SIZES.get(size_label, WATERMARK_SIZES[DEFAULT_WM_SIZE])
    alpha_val = int(255 * opacity_pct / 100)

    w, h = canvas.size
    font = _load_font(font_size, bold=True)

    tmp = Image.new("RGBA", (1, 1))
    tdraw = ImageDraw.Draw(tmp)
    bbox = tdraw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    step_x = max(int(tw * 1.8), font_size * 8)
    step_y = max(int(th * 3.5), font_size * 5)

    diag = int(math.sqrt(w * w + h * h)) + step_x * 2
    layer = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    for yy in range(-step_y, diag + step_y, step_y):
        for xx in range(-step_x, diag + step_x, step_x):
            ld.text((xx, yy), text, font=font, fill=(50, 50, 50, alpha_val))

    rotated = layer.rotate(45, expand=False, resample=Image.BICUBIC)

    rx, ry = rotated.size
    cx = max(0, (rx - w) // 2)
    cy = max(0, (ry - h) // 2)

    cropped = rotated.crop((cx, cy, cx + w, cy + h))
    if cropped.size != (w, h):
        cropped = cropped.resize((w, h), Image.LANCZOS)

    base = canvas.convert("RGBA")
    base = Image.alpha_composite(base, cropped)

    layer.close()
    rotated.close()
    cropped.close()

    return base.convert("RGB")


def _compress(canvas: Image.Image, original_width: int) -> bytes:
    """
    Compress to <= 2 MB. If quality reduction is not enough, reduce dimensions.
    """
    for quality in QUALITY_STEPS:
        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= MAX_FILE_BYTES:
            return data

    for scale in DIMENSION_SCALES:
        nw = max(900, int(original_width * scale))
        nh = max(900, int(canvas.size[1] * scale))

        shrunk = canvas.resize((nw, nh), Image.LANCZOS)
        try:
            for quality in QUALITY_STEPS:
                buf = io.BytesIO()
                shrunk.save(buf, format="JPEG", quality=quality, optimize=True)
                data = buf.getvalue()
                if len(data) <= MAX_FILE_BYTES:
                    return data
        finally:
            shrunk.close()

    # Last fallback: return a compressed image rather than hard-failing.
    # This may be slightly above 2MB only in extreme cases, but normally it will pass.
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=42, optimize=True)
    return buf.getvalue()


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ] if bold else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:/Windows/Fonts/arial.ttf",
        ]
    )

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue

    return ImageFont.load_default()

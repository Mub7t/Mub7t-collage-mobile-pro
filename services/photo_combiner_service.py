"""
photo_combiner_service.py
Memory-safe photo combiner for RL Maintenance Services.

Why this version:
- It uses the same efficient idea as the older collage project.
- It does NOT keep all original high-resolution photos in RAM.
- It opens one image at a time, creates a fitted thumbnail, pastes it, then closes it.
- Final output is compressed to 2 MB or less whenever possible.
"""

from __future__ import annotations

import io
import math
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps


# ── Output target ──────────────────────────────────────────────────────────────
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB

# ── Layout: close to the old fast project ──────────────────────────────────────
CANVAS_WIDTH = 1800
OUTER_PADDING = 60
CELL_GAP = 18
CELL_ASPECT = 0.72  # landscape cell height = width * 0.72
BG_COLOR = (255, 255, 255)
CELL_BG = (255, 255, 255)
CELL_BORDER = (225, 225, 225)

HEADER_HEIGHT = 100
HEADER_FG = (20, 20, 20)

# ── Compression steps ──────────────────────────────────────────────────────────
QUALITY_STEPS = [92, 88, 84, 80, 76, 72, 68, 64, 60, 56, 52, 48, 44]
DIMENSION_SCALES = [0.94, 0.88, 0.82, 0.76, 0.70, 0.64, 0.58, 0.52]

# ── Watermark ──────────────────────────────────────────────────────────────────
WATERMARK_SIZES = {"small": 36, "medium": 58, "large": 86}
DEFAULT_WM_SIZE = "medium"
DEFAULT_WM_OPACITY = 15


# ════════════════════════════════════════════════════════════════════════════════
# Public API used by app.py
# ════════════════════════════════════════════════════════════════════════════════

def combine_photos(
    image_paths: List[str],
    site_name: str = "",
    watermark_text: str = "",
    watermark_opacity: int = DEFAULT_WM_OPACITY,
    watermark_size: str = DEFAULT_WM_SIZE,
    canvas_width: int = CANVAS_WIDTH,
) -> Tuple[bytes, int]:
    """
    Combine many uploaded photos into one compressed JPEG.

    This function intentionally does not load all original photos into memory.
    It calculates the grid first, creates the canvas, then processes images one by one.
    """
    if not image_paths:
        raise ValueError("No images provided.")

    n = len(image_paths)
    cols = _choose_cols(n)
    rows = math.ceil(n / cols)

    pad = OUTER_PADDING
    gap = CELL_GAP

    cell_w = (canvas_width - 2 * pad - gap * (cols - 1)) // cols
    cell_h = round(cell_w * CELL_ASPECT)

    has_header = bool(site_name and site_name.strip())
    header_h = HEADER_HEIGHT if has_header else 0

    canvas_h = header_h + pad + rows * cell_h + (rows - 1) * gap + pad
    canvas = Image.new("RGB", (canvas_width, canvas_h), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    if has_header:
        _draw_header(draw, site_name.strip(), canvas_width, header_h)

    y0 = header_h + pad

    # Critical memory fix: open → thumbnail → paste → close, one file at a time.
    for idx, path in enumerate(image_paths):
        row = idx // cols
        col = idx % cols

        x = pad + col * (cell_w + gap)
        y = y0 + row * (cell_h + gap)

        _draw_cell_background(draw, x, y, cell_w, cell_h)
        _paste_image_file_in_cell(canvas, path, x, y, cell_w, cell_h)

    if watermark_text and watermark_text.strip():
        opacity = max(5, min(40, int(watermark_opacity or DEFAULT_WM_OPACITY)))
        size_label = (watermark_size or DEFAULT_WM_SIZE).lower()
        if size_label not in WATERMARK_SIZES:
            size_label = DEFAULT_WM_SIZE
        canvas = _apply_watermark(canvas, watermark_text.strip(), opacity, size_label)

    data = _compress_under_2mb(canvas)
    canvas.close()
    return data, len(data)


# ════════════════════════════════════════════════════════════════════════════════
# Grid helpers
# ════════════════════════════════════════════════════════════════════════════════

def _choose_cols(n: int) -> int:
    if n <= 1:
        return 1
    if n == 2:
        return 2
    if n == 3:
        return 3
    return 4


def _draw_cell_background(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    draw.rectangle([x, y, x + w, y + h], fill=CELL_BG, outline=CELL_BORDER, width=1)


def _paste_image_file_in_cell(
    canvas: Image.Image,
    path: str,
    cx: int,
    cy: int,
    cell_w: int,
    cell_h: int,
) -> None:
    """Open one image, fix orientation, fit it into the cell, paste it, then close it."""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)

        # Convert safely to RGB, including transparent PNGs.
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, BG_COLOR)
            bg.paste(img, mask=img.getchannel("A"))
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Work only on a cell-sized thumbnail, not the full-resolution original.
        thumb = img.copy()
        thumb.thumbnail((cell_w, cell_h), Image.Resampling.LANCZOS)

        px = cx + (cell_w - thumb.width) // 2
        py = cy + (cell_h - thumb.height) // 2
        canvas.paste(thumb, (px, py))
        thumb.close()


def _draw_header(draw: ImageDraw.ImageDraw, text: str, canvas_width: int, header_h: int) -> None:
    font_size = max(32, header_h // 2)
    font = _load_font(font_size, bold=True)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (canvas_width - tw) // 2
    ty = (header_h - th) // 2
    draw.text((tx, ty), text, fill=HEADER_FG, font=font)


# ════════════════════════════════════════════════════════════════════════════════
# Watermark
# ════════════════════════════════════════════════════════════════════════════════

def _apply_watermark(canvas: Image.Image, text: str, opacity_pct: int, size_label: str) -> Image.Image:
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

    rotated = layer.rotate(45, expand=False, resample=Image.Resampling.BICUBIC)
    rx, ry = rotated.size
    cx = max(0, (rx - w) // 2)
    cy = max(0, (ry - h) // 2)
    cropped = rotated.crop((cx, cy, cx + w, cy + h))

    if cropped.size != (w, h):
        cropped = cropped.resize((w, h), Image.Resampling.LANCZOS)

    base = canvas.convert("RGBA")
    base = Image.alpha_composite(base, cropped)

    layer.close()
    rotated.close()
    cropped.close()

    return base.convert("RGB")


# ════════════════════════════════════════════════════════════════════════════════
# Compression
# ════════════════════════════════════════════════════════════════════════════════

def _compress_under_2mb(canvas: Image.Image) -> bytes:
    rgb = canvas.convert("RGB")

    for quality in QUALITY_STEPS:
        buf = io.BytesIO()
        rgb.save(
            buf,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
            subsampling="4:2:0",
        )
        data = buf.getvalue()
        if len(data) <= MAX_FILE_BYTES:
            rgb.close()
            return data

    original_w, original_h = rgb.size

    for scale in DIMENSION_SCALES:
        nw = max(800, int(original_w * scale))
        nh = max(800, int(original_h * scale))
        shrunk = rgb.resize((nw, nh), Image.Resampling.LANCZOS)

        for quality in QUALITY_STEPS:
            buf = io.BytesIO()
            shrunk.save(
                buf,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
                subsampling="4:2:0",
            )
            data = buf.getvalue()
            if len(data) <= MAX_FILE_BYTES:
                rgb.close()
                shrunk.close()
                return data

        shrunk.close()

    # Last fallback: return compressed output even if extremely detailed images resist 2 MB.
    buf = io.BytesIO()
    rgb.save(
        buf,
        format="JPEG",
        quality=40,
        optimize=True,
        progressive=True,
        subsampling="4:2:0",
    )
    data = buf.getvalue()
    rgb.close()
    return data


# ════════════════════════════════════════════════════════════════════════════════
# Fonts
# ════════════════════════════════════════════════════════════════════════════════

def _load_font(size: int, bold: bool = False):
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
    )

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue

    return ImageFont.load_default()

"""
photo_combiner_service.py  v4
──────────────────────────────
Fixed-cell grid layout matching the reference image (RYDRL 4202 sheet):

Layout rules
────────────
• Canvas: 1800 px wide, 60 px outer padding, 18 px gap between cells
• Column count: 1→1 col, 2→2 col, 3→3 col, 4+→4 col
• Every cell is the SAME fixed size:
      cell_width  = (canvas_width - 2*padding - gap*(cols-1)) / cols
      cell_height = round(cell_width * CELL_ASPECT)   (default 0.72 ≈ 4:3 landscape)
• Each image is scaled with thumbnail() (keeps ratio, fits inside cell)
  then centred on a white cell background.
• Rows are laid out top→bottom; the last partial row is left-aligned.
• Optional site-name header: black text, white bg, centred, ~100 px tall.
• Optional full-canvas 45° tiled watermark applied after grid is built.
• JPEG output compressed to ≤ 2 MB.
"""

from __future__ import annotations

import io
import math
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

# ── Layout constants ───────────────────────────────────────────────────────────
CANVAS_WIDTH   = 1800
OUTER_PADDING  = 60
CELL_GAP       = 18
CELL_ASPECT    = 0.72    # cell_height = cell_width * CELL_ASPECT  (landscape bias)
BG_COLOR       = (255, 255, 255)
HEADER_HEIGHT  = 100     # px for site-name header
HEADER_FG      = (20, 20, 20)

MAX_FILE_BYTES   = 2 * 1024 * 1024
QUALITY_STEPS    = [92, 88, 83, 78, 72, 65, 58]
DIMENSION_SCALES = [0.90, 0.80, 0.70, 0.60]

WATERMARK_SIZES  = {"small": 36, "medium": 58, "large": 86}
DEFAULT_WM_SIZE  = "medium"
DEFAULT_WM_OPACITY = 15


# ── Public API ─────────────────────────────────────────────────────────────────

def combine_photos(
    image_paths: List[str],
    site_name: str       = "",
    watermark_text: str  = "",
    watermark_opacity: int = DEFAULT_WM_OPACITY,
    watermark_size: str  = DEFAULT_WM_SIZE,
    canvas_width: int    = CANVAS_WIDTH,
) -> Tuple[bytes, int]:
    if not image_paths:
        raise ValueError("No images provided.")

    images = _load_images(image_paths)
    canvas = _build_grid(images, site_name, canvas_width)

    if watermark_text and watermark_text.strip():
        opacity  = max(5, min(40, watermark_opacity))
        sz_label = watermark_size.lower() if watermark_size.lower() in WATERMARK_SIZES else DEFAULT_WM_SIZE
        canvas   = _apply_watermark(canvas, watermark_text.strip(), opacity, sz_label)

    data = _compress(canvas, canvas_width)
    return data, len(data)


# ── Image loading ──────────────────────────────────────────────────────────────

def _load_images(paths: List[str]) -> List[Image.Image]:
    out = []
    for p in paths:
        img = Image.open(p)
        img = ImageOps.exif_transpose(img)   # fix phone EXIF rotation
        img = img.convert("RGB")
        out.append(img)
    return out


# ── Grid builder ───────────────────────────────────────────────────────────────

def _choose_cols(n: int) -> int:
    if n <= 1: return 1
    if n == 2: return 2
    if n == 3: return 3
    return 4


def _build_grid(
    images: List[Image.Image],
    site_name: str,
    canvas_width: int,
) -> Image.Image:
    n      = len(images)
    cols   = _choose_cols(n)
    pad    = OUTER_PADDING
    gap    = CELL_GAP

    # Fixed cell dimensions
    cell_w = (canvas_width - 2 * pad - gap * (cols - 1)) // cols
    cell_h = round(cell_w * CELL_ASPECT)

    # Number of rows needed
    rows = math.ceil(n / cols)

    # Total canvas height
    has_header  = bool(site_name and site_name.strip())
    header_h    = HEADER_HEIGHT if has_header else 0
    canvas_h    = (header_h
                   + pad
                   + rows * cell_h
                   + (rows - 1) * gap
                   + pad)

    canvas = Image.new("RGB", (canvas_width, canvas_h), BG_COLOR)
    draw   = ImageDraw.Draw(canvas)

    # Draw site-name header
    if has_header:
        _draw_header(draw, site_name.strip(), canvas_width, header_h)

    # Starting y for first image row
    y0 = header_h + pad

    for idx, img in enumerate(images):
        row = idx // cols
        col = idx  % cols

        x = pad + col * (cell_w + gap)
        y = y0  + row * (cell_h + gap)

        _paste_in_cell(canvas, img, x, y, cell_w, cell_h)

    return canvas


def _paste_in_cell(
    canvas: Image.Image,
    img: Image.Image,
    cx: int, cy: int,
    cell_w: int, cell_h: int,
) -> None:
    """
    Scale img so it fits entirely inside the cell (no cropping, no distortion),
    then centre it.  White padding fills any remaining space.
    """
    iw, ih = img.size

    # Scale to fit inside cell, preserving ratio
    scale  = min(cell_w / iw, cell_h / ih)
    new_w  = max(1, round(iw * scale))
    new_h  = max(1, round(ih * scale))

    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # Centre offset within cell
    off_x = cx + (cell_w - new_w) // 2
    off_y = cy + (cell_h - new_h) // 2

    canvas.paste(resized, (off_x, off_y))


# ── Header ─────────────────────────────────────────────────────────────────────

def _draw_header(
    draw: ImageDraw.ImageDraw,
    text: str,
    canvas_width: int,
    header_h: int,
) -> None:
    font_size = max(32, header_h // 2)
    font      = _load_font(font_size, bold=True)
    bbox      = draw.textbbox((0, 0), text, font=font)
    tw        = bbox[2] - bbox[0]
    th        = bbox[3] - bbox[1]
    tx        = (canvas_width - tw) // 2
    ty        = (header_h - th) // 2
    draw.text((tx, ty), text, fill=HEADER_FG, font=font)


# ── Watermark ──────────────────────────────────────────────────────────────────

def _apply_watermark(
    canvas: Image.Image,
    text: str,
    opacity_pct: int,
    size_label: str,
) -> Image.Image:
    font_size = WATERMARK_SIZES.get(size_label, WATERMARK_SIZES[DEFAULT_WM_SIZE])
    alpha_val = int(255 * opacity_pct / 100)
    w, h      = canvas.size
    font      = _load_font(font_size, bold=True)

    # Measure text
    tmp  = Image.new("RGBA", (1, 1))
    tdraw = ImageDraw.Draw(tmp)
    bbox  = tdraw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    step_x = max(int(tw * 1.8), font_size * 8)
    step_y = max(int(th * 3.5), font_size * 5)

    # Build oversized transparent tile layer
    diag  = int(math.sqrt(w * w + h * h)) + step_x * 2
    layer = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    ld    = ImageDraw.Draw(layer)
    for yy in range(-step_y, diag + step_y, step_y):
        for xx in range(-step_x, diag + step_x, step_x):
            ld.text((xx, yy), text, font=font, fill=(50, 50, 50, alpha_val))

    rotated = layer.rotate(45, expand=False, resample=Image.BICUBIC)
    rx, ry  = rotated.size
    cx      = max(0, (rx - w) // 2)
    cy      = max(0, (ry - h) // 2)
    cropped = rotated.crop((cx, cy, cx + w, cy + h))
    if cropped.size != (w, h):
        cropped = cropped.resize((w, h), Image.LANCZOS)

    base = canvas.convert("RGBA")
    base = Image.alpha_composite(base, cropped)
    return base.convert("RGB")


# ── Compression ────────────────────────────────────────────────────────────────

def _compress(canvas: Image.Image, original_width: int) -> bytes:
    for quality in QUALITY_STEPS:
        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= MAX_FILE_BYTES:
            return data

    for scale in DIMENSION_SCALES:
        nw = int(original_width * scale)
        nh = int(canvas.size[1] * scale)
        shrunk = canvas.resize((nw, nh), Image.LANCZOS)
        for quality in QUALITY_STEPS:
            buf = io.BytesIO()
            shrunk.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
            if len(data) <= MAX_FILE_BYTES:
                return data

    raise ValueError(
        "Could not compress the combined image to under 2 MB. "
        "Please use fewer photos or smaller images."
    )


# ── Font loader ────────────────────────────────────────────────────────────────

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

"""
photo_combiner_service.py
────────────────────────
Memory-safe grouped photo combiner for RL Maintenance Services.

What this version does:
- Keeps the stable memory-safe behavior.
- Scans only image metadata first to classify image orientation.
- Groups landscape photos together.
- Groups portrait photos together.
- Opens, resizes, pastes, and closes one image at a time.
- Compresses the final JPG to <= 2 MB when possible.

This is designed to stay compatible with Render free instance constraints while
producing a cleaner collage layout.
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
SECTION_GAP = 28
BG_COLOR = (255, 255, 255)
CELL_BORDER = (232, 232, 232)

HEADER_HEIGHT = 100
HEADER_FG = (20, 20, 20)

LANDSCAPE_CELL_ASPECT = 0.68
PORTRAIT_CELL_ASPECT = 1.28

MAX_FILE_BYTES = 2 * 1024 * 1024
QUALITY_STEPS = [92, 88, 83, 78, 72, 65, 58, 52, 46]
DIMENSION_SCALES = [0.92, 0.84, 0.76, 0.68, 0.60, 0.52]

WATERMARK_SIZES = {"small": 36, "medium": 58, "large": 86}
DEFAULT_WM_SIZE = "medium"
DEFAULT_WM_OPACITY = 15

ORIENTATION_TAG = 274
ROTATE_90 = {5, 6, 7, 8}


def combine_photos(
    image_paths: List[str],
    site_name: str = "",
    watermark_text: str = "",
    watermark_opacity: int = DEFAULT_WM_OPACITY,
    watermark_size: str = DEFAULT_WM_SIZE,
    canvas_width: int = CANVAS_WIDTH,
) -> Tuple[bytes, int]:
    if not image_paths:
        raise ValueError("No images provided.")

    landscape_paths, portrait_paths = _group_paths_by_orientation(image_paths)

    pad = OUTER_PADDING
    gap = CELL_GAP
    header_h = HEADER_HEIGHT if site_name and site_name.strip() else 0

    # Landscape section layout
    land_cols = _choose_landscape_cols(len(landscape_paths)) if landscape_paths else 0
    if land_cols:
        land_cell_w = (canvas_width - 2 * pad - gap * (land_cols - 1)) // land_cols
        land_cell_h = round(land_cell_w * LANDSCAPE_CELL_ASPECT)
        land_rows = math.ceil(len(landscape_paths) / land_cols)
        land_section_h = land_rows * land_cell_h + max(0, land_rows - 1) * gap
    else:
        land_cell_w = land_cell_h = land_rows = land_section_h = 0

    # Portrait section layout
    port_cols = _choose_portrait_cols(len(portrait_paths)) if portrait_paths else 0
    if port_cols:
        port_cell_w = (canvas_width - 2 * pad - gap * (port_cols - 1)) // port_cols
        port_cell_h = round(port_cell_w * PORTRAIT_CELL_ASPECT)
        port_rows = math.ceil(len(portrait_paths) / port_cols)
        port_section_h = port_rows * port_cell_h + max(0, port_rows - 1) * gap
    else:
        port_cell_w = port_cell_h = port_rows = port_section_h = 0

    middle_gap = SECTION_GAP if (land_section_h and port_section_h) else 0
    canvas_h = header_h + pad + land_section_h + middle_gap + port_section_h + pad

    canvas = Image.new("RGB", (canvas_width, canvas_h), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    if site_name and site_name.strip():
        _draw_header(draw, site_name.strip(), canvas_width, header_h)

    current_y = header_h + pad

    if landscape_paths:
        _draw_path_section(
            canvas=canvas,
            paths=landscape_paths,
            start_y=current_y,
            cols=land_cols,
            cell_w=land_cell_w,
            cell_h=land_cell_h,
            pad=pad,
            gap=gap,
        )
        current_y += land_section_h

    if landscape_paths and portrait_paths:
        current_y += middle_gap

    if portrait_paths:
        _draw_path_section(
            canvas=canvas,
            paths=portrait_paths,
            start_y=current_y,
            cols=port_cols,
            cell_w=port_cell_w,
            cell_h=port_cell_h,
            pad=pad,
            gap=gap,
        )

    if watermark_text and watermark_text.strip():
        opacity = max(5, min(40, int(watermark_opacity or DEFAULT_WM_OPACITY)))
        size_key = (watermark_size or DEFAULT_WM_SIZE).lower()
        if size_key not in WATERMARK_SIZES:
            size_key = DEFAULT_WM_SIZE
        canvas = _apply_watermark(canvas, watermark_text.strip(), opacity, size_key)

    data = _compress(canvas, canvas_width)
    canvas.close()
    return data, len(data)


# ── Orientation grouping ──────────────────────────────────────────────────────

def _group_paths_by_orientation(image_paths: List[str]) -> Tuple[List[str], List[str]]:
    landscapes: List[str] = []
    portraits: List[str] = []

    for path in image_paths:
        w, h = _read_effective_dimensions(path)
        ratio = (w / h) if h else 1.0
        if ratio >= 0.95:
            landscapes.append(path)
        else:
            portraits.append(path)

    return landscapes, portraits


def _read_effective_dimensions(path: str) -> Tuple[int, int]:
    """
    Read width/height cheaply without fully decoding the image.
    Respect EXIF orientation for classification only.
    """
    with Image.open(path) as img:
        w, h = img.size
        try:
            exif = img.getexif()
            orientation = exif.get(ORIENTATION_TAG)
            if orientation in ROTATE_90:
                w, h = h, w
        except Exception:
            pass
        return w, h


# ── Grid helpers ──────────────────────────────────────────────────────────────

def _choose_landscape_cols(n: int) -> int:
    if n <= 1:
        return 1
    if n == 2:
        return 2
    if n <= 6:
        return 3
    return 4


def _choose_portrait_cols(n: int) -> int:
    if n <= 1:
        return 1
    if n == 2:
        return 2
    if n <= 6:
        return 3
    if n <= 12:
        return 4
    return 5


def _draw_path_section(
    canvas: Image.Image,
    paths: List[str],
    start_y: int,
    cols: int,
    cell_w: int,
    cell_h: int,
    pad: int,
    gap: int,
) -> None:
    for idx, path in enumerate(paths):
        row = idx // cols
        col = idx % cols
        x = pad + col * (cell_w + gap)
        y = start_y + row * (cell_h + gap)
        _paste_path_in_cell(canvas, path, x, y, cell_w, cell_h)


def _paste_path_in_cell(
    canvas: Image.Image,
    path: str,
    x: int,
    y: int,
    cell_w: int,
    cell_h: int,
) -> None:
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
        try:
            paste_x = x + (cell_w - new_w) // 2
            paste_y = y + (cell_h - new_h) // 2
            canvas.paste(resized, (paste_x, paste_y))
        finally:
            resized.close()
    finally:
        try:
            img.close()
        except Exception:
            pass


# ── Header ────────────────────────────────────────────────────────────────────

def _draw_header(draw: ImageDraw.ImageDraw, text: str, canvas_width: int, header_h: int) -> None:
    font_size = max(32, header_h // 2)
    font = _load_font(font_size, bold=True)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    tx = (canvas_width - tw) // 2
    ty = (header_h - th) // 2
    draw.text((tx, ty), text, fill=HEADER_FG, font=font)


# ── Watermark ─────────────────────────────────────────────────────────────────

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

    rotated = layer.rotate(45, expand=False, resample=Image.BICUBIC)
    rx, ry = rotated.size
    cx = max(0, (rx - w) // 2)
    cy = max(0, (ry - h) // 2)

    cropped = rotated.crop((cx, cy, cx + w, cy + h))
    if cropped.size != (w, h):
        cropped = cropped.resize((w, h), Image.LANCZOS)

    base = canvas.convert("RGBA")
    result = Image.alpha_composite(base, cropped).convert("RGB")

    tmp.close()
    layer.close()
    rotated.close()
    cropped.close()
    base.close()

    return result


# ── Compression ───────────────────────────────────────────────────────────────

def _compress(canvas: Image.Image, original_width: int) -> bytes:
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

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=42, optimize=True)
    return buf.getvalue()


# ── Font loader ───────────────────────────────────────────────────────────────

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

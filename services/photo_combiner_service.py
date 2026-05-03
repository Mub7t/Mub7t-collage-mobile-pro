"""
photo_combiner_service.py
────────────────────────
Grouped collage layout for RL Maintenance Services.

Goal
────
Arrange landscape photos next to landscape photos, and portrait photos next to
portrait photos, so the final sheet looks cleaner and more professional.

Behavior
────────
• Landscape images are grouped together in the first section.
• Portrait images are grouped together in a separate section below.
• Near-square images are treated with landscape images.
• Each section has its own fixed cell dimensions.
• Images are fitted inside white cells without cropping or distortion.
• Optional centered site-name header.
• Optional diagonal tiled watermark over the final canvas.
• Final JPG is compressed to ≤ 2 MB.
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
HEADER_HEIGHT = 100
HEADER_FG = (20, 20, 20)
CELL_BORDER = (232, 232, 232)

# Group-specific layout tuning
LANDSCAPE_CELL_ASPECT = 0.62   # shorter cells for wide photos
PORTRAIT_CELL_ASPECT = 1.34    # taller cells for portrait photos

MAX_FILE_BYTES = 2 * 1024 * 1024
QUALITY_STEPS = [92, 88, 83, 78, 72, 65, 58]
DIMENSION_SCALES = [0.90, 0.80, 0.70, 0.60]

WATERMARK_SIZES = {"small": 36, "medium": 58, "large": 86}
DEFAULT_WM_SIZE = "medium"
DEFAULT_WM_OPACITY = 15


# ── Public API ─────────────────────────────────────────────────────────────────

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

    images = _load_images(image_paths)
    landscape_images, portrait_images = _group_images(images)
    canvas = _build_grouped_grid(landscape_images, portrait_images, site_name, canvas_width)

    if watermark_text and watermark_text.strip():
        opacity = max(5, min(40, int(watermark_opacity or DEFAULT_WM_OPACITY)))
        size_key = (watermark_size or DEFAULT_WM_SIZE).lower()
        if size_key not in WATERMARK_SIZES:
            size_key = DEFAULT_WM_SIZE
        canvas = _apply_watermark(canvas, watermark_text.strip(), opacity, size_key)

    data = _compress(canvas, canvas_width)
    return data, len(data)


# ── Image loading and grouping ────────────────────────────────────────────────

def _load_images(paths: List[str]) -> List[Image.Image]:
    loaded: List[Image.Image] = []
    for path in paths:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        loaded.append(img)
    return loaded


def _group_images(images: List[Image.Image]) -> Tuple[List[Image.Image], List[Image.Image]]:
    """
    Group images into landscape and portrait buckets.
    Near-square images are treated as landscape so they stay with the wider row style.
    """
    landscapes: List[Image.Image] = []
    portraits: List[Image.Image] = []

    for img in images:
        w, h = img.size
        ratio = w / h if h else 1

        if ratio >= 0.95:
            landscapes.append(img)
        else:
            portraits.append(img)

    return landscapes, portraits


# ── Grid builder ───────────────────────────────────────────────────────────────

def _choose_cols_for_landscape(n: int) -> int:
    if n <= 1:
        return 1
    if n == 2:
        return 2
    if n <= 4:
        return 2
    if n <= 9:
        return 3
    return 4


def _choose_cols_for_portrait(n: int) -> int:
    if n <= 1:
        return 1
    if n == 2:
        return 2
    if n <= 6:
        return 3
    if n <= 12:
        return 4
    return 5


def _section_height(n: int, cols: int, cell_h: int, gap: int) -> int:
    if n == 0:
        return 0
    rows = math.ceil(n / cols)
    return rows * cell_h + max(0, rows - 1) * gap


def _build_grouped_grid(
    landscape_images: List[Image.Image],
    portrait_images: List[Image.Image],
    site_name: str,
    canvas_width: int,
) -> Image.Image:
    pad = OUTER_PADDING
    gap = CELL_GAP

    # Landscape section sizing
    land_cols = _choose_cols_for_landscape(len(landscape_images)) if landscape_images else 0
    land_cell_w = (canvas_width - 2 * pad - gap * (land_cols - 1)) // land_cols if land_cols else 0
    land_cell_h = round(land_cell_w * LANDSCAPE_CELL_ASPECT) if land_cols else 0
    land_h = _section_height(len(landscape_images), land_cols, land_cell_h, gap)

    # Portrait section sizing
    port_cols = _choose_cols_for_portrait(len(portrait_images)) if portrait_images else 0
    port_cell_w = (canvas_width - 2 * pad - gap * (port_cols - 1)) // port_cols if port_cols else 0
    port_cell_h = round(port_cell_w * PORTRAIT_CELL_ASPECT) if port_cols else 0
    port_h = _section_height(len(portrait_images), port_cols, port_cell_h, gap)

    has_header = bool(site_name and site_name.strip())
    header_h = HEADER_HEIGHT if has_header else 0

    middle_gap = SECTION_GAP if (land_h and port_h) else 0
    canvas_h = header_h + pad + land_h + middle_gap + port_h + pad

    canvas = Image.new("RGB", (canvas_width, canvas_h), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    if has_header:
        _draw_header(draw, site_name.strip(), canvas_width, header_h)

    y = header_h + pad

    if landscape_images:
        _draw_section(
            canvas=canvas,
            images=landscape_images,
            start_y=y,
            cols=land_cols,
            cell_w=land_cell_w,
            cell_h=land_cell_h,
            pad=pad,
            gap=gap,
        )
        y += land_h

    if landscape_images and portrait_images:
        y += middle_gap

    if portrait_images:
        _draw_section(
            canvas=canvas,
            images=portrait_images,
            start_y=y,
            cols=port_cols,
            cell_w=port_cell_w,
            cell_h=port_cell_h,
            pad=pad,
            gap=gap,
        )

    return canvas


def _draw_section(
    canvas: Image.Image,
    images: List[Image.Image],
    start_y: int,
    cols: int,
    cell_w: int,
    cell_h: int,
    pad: int,
    gap: int,
) -> None:
    for idx, img in enumerate(images):
        row = idx // cols
        col = idx % cols
        x = pad + col * (cell_w + gap)
        y = start_y + row * (cell_h + gap)
        _paste_in_cell(canvas, img, x, y, cell_w, cell_h)


def _paste_in_cell(
    canvas: Image.Image,
    img: Image.Image,
    x: int,
    y: int,
    cell_w: int,
    cell_h: int,
) -> None:
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([x, y, x + cell_w, y + cell_h], outline=CELL_BORDER, fill=BG_COLOR)

    iw, ih = img.size
    scale = min(cell_w / iw, cell_h / ih)
    new_w = max(1, round(iw * scale))
    new_h = max(1, round(ih * scale))

    resized = img.resize((new_w, new_h), Image.LANCZOS)

    paste_x = x + (cell_w - new_w) // 2
    paste_y = y + (cell_h - new_h) // 2
    canvas.paste(resized, (paste_x, paste_y))


# ── Header ─────────────────────────────────────────────────────────────────────

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


# ── Watermark ──────────────────────────────────────────────────────────────────

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
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    step_x = max(int(tw * 1.8), font_size * 8)
    step_y = max(int(th * 3.5), font_size * 5)

    diag = int(math.sqrt(w * w + h * h)) + step_x * 2
    layer = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for yy in range(-step_y, diag + step_y, step_y):
        for xx in range(-step_x, diag + step_x, step_x):
            ld.text((xx, yy), text, font=font, fill=(70, 70, 70, alpha_val))

    rotated = layer.rotate(45, expand=False, resample=Image.BICUBIC)
    rx, ry = rotated.size
    cx = max(0, (rx - w) // 2)
    cy = max(0, (ry - h) // 2)
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

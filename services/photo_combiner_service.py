"""
Photo Combiner Service
- Accepts high-resolution uploaded images
- Downscales internally for processing
- Combines multiple photos into one image
- Adds optional site header and diagonal watermark
- Compresses final JPG under target size
"""

from io import BytesIO
from math import ceil, sqrt
from PIL import Image, ImageDraw, ImageFont, ImageOps


TARGET_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
PROCESS_MAX_SIDE = 1600             # Internal working size per photo
FINAL_MAX_SIDE = 3200               # Final combined image max side
BACKGROUND = (255, 255, 255)


def combine_photos(
    image_paths,
    site_name="",
    watermark_text="",
    watermark_opacity=15,
    watermark_size="medium",
):
    if not image_paths:
        raise ValueError("Please upload at least one photo.")

    images = []

    for path in image_paths:
        img = Image.open(path)

        # Fix mobile camera orientation
        img = ImageOps.exif_transpose(img)

        # Convert safely to RGB
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        elif img.mode == "RGBA":
            bg = Image.new("RGB", img.size, BACKGROUND)
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")

        # Critical: reduce memory usage internally only
        img.thumbnail((PROCESS_MAX_SIDE, PROCESS_MAX_SIDE), Image.Resampling.LANCZOS)

        images.append(img.copy())
        img.close()

    count = len(images)

    # Grid layout
    cols = ceil(sqrt(count))
    rows = ceil(count / cols)

    # Use consistent tile size based on processed images
    max_w = max(img.width for img in images)
    max_h = max(img.height for img in images)

    tile_w = max_w
    tile_h = max_h

    padding = 16
    header_h = 0

    site_name = (site_name or "").strip()
    if site_name:
        header_h = 90

    canvas_w = cols * tile_w + (cols + 1) * padding
    canvas_h = rows * tile_h + (rows + 1) * padding + header_h

    combined = Image.new("RGB", (canvas_w, canvas_h), BACKGROUND)
    draw = ImageDraw.Draw(combined)

    # Fonts
    title_font = _load_font(38, bold=True)
    normal_font = _load_font(24, bold=False)

    # Header
    if site_name:
        draw.rectangle([0, 0, canvas_w, header_h], fill=(245, 245, 245))
        draw.text(
            (padding, 24),
            site_name,
            fill=(0, 0, 0),
            font=title_font,
        )

    # Paste images centered inside each tile
    y_start = header_h + padding

    for i, img in enumerate(images):
        row = i // cols
        col = i % cols

        x = padding + col * (tile_w + padding)
        y = y_start + row * (tile_h + padding)

        # White tile background
        draw.rectangle(
            [x, y, x + tile_w, y + tile_h],
            fill=(255, 255, 255),
            outline=(220, 220, 220),
            width=1,
        )

        px = x + (tile_w - img.width) // 2
        py = y + (tile_h - img.height) // 2

        combined.paste(img, (px, py))

    # Add diagonal watermark
    watermark_text = (watermark_text or "").strip()
    if watermark_text:
        combined = _apply_watermark(
            combined,
            watermark_text,
            opacity=watermark_opacity,
            size=watermark_size,
        )

    # Reduce final dimensions if too large
    combined.thumbnail((FINAL_MAX_SIDE, FINAL_MAX_SIDE), Image.Resampling.LANCZOS)

    jpeg_bytes = _compress_under_size(combined, TARGET_MAX_BYTES)

    for img in images:
        img.close()

    combined.close()

    return jpeg_bytes, len(jpeg_bytes)


def _compress_under_size(image, target_bytes):
    """
    Compress final JPG until it is under target_bytes.
    If quality reduction is not enough, slightly reduce dimensions.
    """
    working = image.copy()

    # First try quality reduction
    for quality in [92, 88, 85, 82, 80, 76, 72, 68, 64, 60, 56, 52, 48]:
        buffer = BytesIO()
        working.save(
            buffer,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
        )
        data = buffer.getvalue()

        if len(data) <= target_bytes:
            working.close()
            return data

    # If still too large, reduce dimensions gradually
    scale_steps = [0.92, 0.86, 0.80, 0.74, 0.68, 0.62, 0.56, 0.50]

    for scale in scale_steps:
        new_w = max(800, int(working.width * scale))
        new_h = max(800, int(working.height * scale))

        resized = working.resize((new_w, new_h), Image.Resampling.LANCZOS)

        for quality in [82, 76, 70, 64, 58, 52, 46, 40]:
            buffer = BytesIO()
            resized.save(
                buffer,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )
            data = buffer.getvalue()

            if len(data) <= target_bytes:
                working.close()
                resized.close()
                return data

        working.close()
        working = resized

    # Last fallback
    buffer = BytesIO()
    working.save(
        buffer,
        format="JPEG",
        quality=38,
        optimize=True,
        progressive=True,
    )
    data = buffer.getvalue()
    working.close()
    return data


def _apply_watermark(image, text, opacity=15, size="medium"):
    opacity = max(5, min(40, int(opacity or 15)))

    w, h = image.size
    overlay = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    if size == "small":
        font_size = max(38, int(min(w, h) * 0.045))
        spacing = 260
    elif size == "large":
        font_size = max(70, int(min(w, h) * 0.080))
        spacing = 420
    else:
        font_size = max(52, int(min(w, h) * 0.060))
        spacing = 340

    font = _load_font(font_size, bold=True)

    alpha = int(255 * (opacity / 100))
    fill = (0, 0, 0, alpha)

    # Create a large rotated watermark layer
    wm_layer = Image.new("RGBA", (w * 2, h * 2), (255, 255, 255, 0))
    wm_draw = ImageDraw.Draw(wm_layer)

    for y in range(-h, h * 2, spacing):
        for x in range(-w, w * 2, spacing):
            wm_draw.text((x, y), text, fill=fill, font=font)

    wm_layer = wm_layer.rotate(-35, expand=False)

    crop_x = (wm_layer.width - w) // 2
    crop_y = (wm_layer.height - h) // 2
    wm_layer = wm_layer.crop((crop_x, crop_y, crop_x + w, crop_y + h))

    combined = Image.alpha_composite(image.convert("RGBA"), wm_layer)
    return combined.convert("RGB")


def _load_font(size, bold=False):
    font_candidates = []

    if bold:
        font_candidates = [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    else:
        font_candidates = [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]

    for font_path in font_candidates:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass

    return ImageFont.load_default()
from __future__ import annotations
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

def load_font(font_path: Optional[str], font_size: int):
    if font_path:
        try:
            return ImageFont.truetype(font_path, font_size)
        except OSError:
            pass
    try:
        return ImageFont.truetype("DejaVuSans.ttf", font_size)
    except OSError:
        return ImageFont.load_default()

def text_bbox(text: str, font) -> tuple[int, int]:
    dummy = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(dummy)
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]

def compute_x(text_width: int, canvas_width: int, align: str, margin: int) -> int:
    if align == "left":
        return margin
    if align == "right":
        return max(margin, canvas_width - margin - text_width)
    return max(margin, (canvas_width - text_width) // 2)

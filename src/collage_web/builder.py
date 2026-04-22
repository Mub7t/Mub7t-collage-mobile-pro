from __future__ import annotations
from pathlib import Path
from typing import Iterable
from PIL import Image, ImageDraw
from .compression import save_under_size
from .forms import CollageOptions
from .text_utils import compute_x, load_font, text_bbox
from .utils import calculate_grid, contain_image

def build_collage(
    image_paths: Iterable[Path],
    output_path: Path,
    options: CollageOptions,
    font_path: str | None = None,
) -> Path:
    paths = list(image_paths)
    if not paths:
        raise ValueError("At least one image is required.")
    options.validate()

    cols, rows = calculate_grid(len(paths))
    cell_w = options.cell_size
    cell_h = options.cell_size
    outer_margin = 24

    width = cols * cell_w + (cols - 1) * options.padding + outer_margin * 2
    grid_height = rows * cell_h + (rows - 1) * options.padding

    title_block = 0
    font = load_font(font_path, options.font_size)
    if options.title.strip():
        _, th = text_bbox(options.title, font)
        title_block = th + 48

    height = grid_height + title_block + outer_margin * 2
    canvas = Image.new("RGB", (width, height), options.background)

    if options.title.strip():
        draw = ImageDraw.Draw(canvas)
        tw, _ = text_bbox(options.title, font)
        tx = compute_x(tw, width, options.align, outer_margin)
        ty = outer_margin + 10
        draw.text((tx, ty), options.title, font=font, fill=options.title_color)

    grid_top = outer_margin + title_block

    for idx, path in enumerate(paths):
        row = idx // cols
        col = idx % cols
        x = outer_margin + col * (cell_w + options.padding)
        y = grid_top + row * (cell_h + options.padding)

        with Image.open(path) as img:
            thumb = contain_image(img, cell_w, cell_h)
            px = x + (cell_w - thumb.width) // 2
            py = y + (cell_h - thumb.height) // 2
            canvas.paste(thumb, (px, py))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    return save_under_size(canvas, output_path, options.max_size_mb)

from __future__ import annotations
from io import BytesIO
from pathlib import Path
from PIL import Image

def save_under_size(
    image: Image.Image,
    output_path: Path,
    max_size_mb: float,
    quality_start: int = 95,
    quality_min: int = 45,
) -> Path:
    max_bytes = int(max_size_mb * 1024 * 1024)
    original = image.convert("RGB")

    last_working = original
    for scale in (1.0, 0.94, 0.88, 0.82, 0.76, 0.70, 0.64):
        if scale == 1.0:
            working = original
        else:
            new_size = (
                max(1, int(original.width * scale)),
                max(1, int(original.height * scale)),
            )
            working = original.resize(new_size, Image.Resampling.LANCZOS)

        last_working = working
        for quality in range(quality_start, quality_min - 1, -5):
            buf = BytesIO()
            working.save(
                buf,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
                subsampling="4:2:0",
            )
            data = buf.getvalue()
            if len(data) <= max_bytes:
                output_path.write_bytes(data)
                return output_path

    buf = BytesIO()
    last_working.save(
        buf,
        format="JPEG",
        quality=quality_min,
        optimize=True,
        progressive=True,
        subsampling="4:2:0",
    )
    output_path.write_bytes(buf.getvalue())
    return output_path

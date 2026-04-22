from __future__ import annotations
from dataclasses import dataclass

@dataclass(slots=True)
class CollageOptions:
    title: str = ""
    font_size: int = 40
    align: str = "center"
    max_size_mb: float = 8.0
    cell_size: int = 420
    padding: int = 14
    background: tuple[int, int, int] = (255, 255, 255)
    title_color: tuple[int, int, int] = (0, 0, 0)

    def validate(self) -> None:
        if self.align not in {"left", "center", "right"}:
            raise ValueError("Alignment must be left, center, or right.")
        if self.font_size < 12 or self.font_size > 160:
            raise ValueError("Font size must be between 12 and 160.")
        if self.max_size_mb <= 0:
            raise ValueError("Max size must be greater than 0.")
        if self.cell_size < 120 or self.cell_size > 1600:
            raise ValueError("Cell size must be between 120 and 1600.")
        if self.padding < 0 or self.padding > 100:
            raise ValueError("Padding must be between 0 and 100.")

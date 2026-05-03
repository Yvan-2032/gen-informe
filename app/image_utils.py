from __future__ import annotations

from pathlib import Path

from PIL import Image, UnidentifiedImageError


def is_image_loadable(image_path: str) -> bool:
    path = Path(image_path)
    if not path.exists() or not path.is_file():
        return False

    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except (UnidentifiedImageError, OSError):
        return False


def calculate_fit_size_inches(
    image_path: str, max_width_in: float, max_height_in: float
) -> tuple[float, float]:
    with Image.open(image_path) as img:
        width_px, height_px = img.size

    if width_px <= 0 or height_px <= 0:
        return max_width_in, max_height_in

    ratio = min(max_width_in / width_px, max_height_in / height_px)
    return width_px * ratio, height_px * ratio

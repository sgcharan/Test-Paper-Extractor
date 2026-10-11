"""PDF rendering and structure cropping helpers."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from pdf2image import convert_from_path
from PIL import Image

from schemas import StructureRef


def resize_for_vlm(image: Image.Image, max_side: int = 1280) -> Image.Image:
    """Downscale page image for VLM inference; crops still use full-resolution render."""
    w, h = image.size
    longest = max(w, h)
    if longest <= max_side:
        return image
    scale = max_side / longest
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def render_pdf_page(
    pdf_path: str,
    page_index: int,
    dpi: int = 300,
    poppler_path: Optional[str] = None,
) -> Image.Image:
    kwargs = {"dpi": dpi, "first_page": page_index + 1, "last_page": page_index + 1}
    if poppler_path:
        kwargs["poppler_path"] = poppler_path
    pages = convert_from_path(pdf_path, **kwargs)
    if not pages:
        raise ValueError(f"No page rendered for index {page_index} in {pdf_path}")
    return pages[0]


def count_pdf_pages(pdf_path: str, poppler_path: Optional[str] = None) -> int:
    kwargs = {}
    if poppler_path:
        kwargs["poppler_path"] = poppler_path
    from pdf2image.pdf2image import pdfinfo_from_path

    info = pdfinfo_from_path(pdf_path, **kwargs)
    return int(info["Pages"])


def denorm_bbox(bbox_norm: List[float], width: int, height: int) -> Tuple[int, int, int, int]:
    if len(bbox_norm) != 4:
        raise ValueError(f"bbox_norm must have 4 values, got {bbox_norm}")
    x1, y1, x2, y2 = bbox_norm
    left = int(min(x1, x2) / 1000.0 * width)
    right = int(max(x1, x2) / 1000.0 * width)
    top = int(min(y1, y2) / 1000.0 * height)
    bottom = int(max(y1, y2) / 1000.0 * height)
    return left, top, right, bottom


def pad_bbox(
    box: Tuple[int, int, int, int],
    width: int,
    height: int,
    padding_ratio: float = 0.03,
) -> Tuple[int, int, int, int]:
    left, top, right, bottom = box
    pad_x = int((right - left) * padding_ratio)
    pad_y = int((bottom - top) * padding_ratio)
    left = max(0, left - pad_x)
    top = max(0, top - pad_y)
    right = min(width, right + pad_x)
    bottom = min(height, bottom + pad_y)
    if right <= left:
        right = min(width, left + 1)
    if bottom <= top:
        bottom = min(height, top + 1)
    return left, top, right, bottom


def crop_structure(
    page_image: Image.Image,
    structure: StructureRef,
    padding_ratio: float = 0.03,
) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
    w, h = page_image.size
    box = denorm_bbox(structure.bbox_norm, w, h)
    box = pad_bbox(box, w, h, padding_ratio=padding_ratio)
    crop = page_image.crop(box)
    return crop, box


def save_crop(crop: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(path, format="PNG")

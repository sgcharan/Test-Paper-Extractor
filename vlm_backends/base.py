"""Abstract interface for vision backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

    from schemas import PageExtraction


class VisionBackend(ABC):
    @abstractmethod
    def extract_page(self, page_image: Image.Image, page_index: int) -> PageExtraction:
        """Run VLM on a single page image and return structured extraction."""

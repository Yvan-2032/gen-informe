from __future__ import annotations

from abc import ABC, abstractmethod


class OcrError(RuntimeError):
    """Base OCR error used by UI for consistent messaging."""


class OcrDependencyError(OcrError):
    """Required OCR dependency is missing or broken."""


class OcrModelLoadError(OcrError):
    """OCR model could not be loaded."""


class OcrRuntimeError(OcrError):
    """OCR execution failed."""


class OcrEngine(ABC):
    @abstractmethod
    def run_ocr(self, image_path: str, source_language: str) -> str:
        """Run OCR on image_path and return recognized text."""

    def get_last_warning(self) -> str | None:
        return None


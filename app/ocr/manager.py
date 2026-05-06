from __future__ import annotations

from app.ocr.base import OcrEngine
from app.ocr.easyocr_engine import EasyOcrEngine

_ACTIVE_BACKEND = "easyocr"
_ENGINE: OcrEngine | None = None


def get_ocr_engine() -> OcrEngine:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    if _ACTIVE_BACKEND == "easyocr":
        _ENGINE = EasyOcrEngine()
        return _ENGINE

    # Future extension point:
    # if _ACTIVE_BACKEND == "paddleocr":
    #     _ENGINE = PaddleOcrEngine()
    #     return _ENGINE
    raise RuntimeError(f"Backend OCR no soportado: {_ACTIVE_BACKEND}")


def run_ocr(image_path: str, source_language: str) -> str:
    engine = get_ocr_engine()
    return engine.run_ocr(image_path, source_language)


def get_last_ocr_warning() -> str | None:
    engine = get_ocr_engine()
    return engine.get_last_warning()


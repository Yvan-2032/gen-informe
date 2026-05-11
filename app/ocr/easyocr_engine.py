from __future__ import annotations

import threading
from pathlib import Path

from app.ocr.base import OcrDependencyError, OcrEngine, OcrModelLoadError, OcrRuntimeError


def _normalize_language_name(value: str) -> str:
    text = str(value or "").strip().casefold()
    if "mixt" in text:
        return "mixed"
    if "ingl" in text or "english" in text:
        return "english"
    if "japon" in text or "japanese" in text:
        return "japanese"
    if "espa" in text or "spanish" in text:
        return "spanish"
    if "chino" in text and "trad" in text:
        return "chinese_traditional"
    if "chino" in text:
        return "chinese_simple"

    aliases = {
        "ingles": "english",
        "inglés": "english",
        "inglã©s": "english",
        "english": "english",
        "japones": "japanese",
        "japonés": "japanese",
        "japonã©s": "japanese",
        "japanese": "japanese",
        "chino": "chinese_simple",
        "chino simplificado": "chinese_simple",
        "chino tradicional": "chinese_traditional",
        "espanol": "spanish",
        "español": "spanish",
        "espaã±ol": "spanish",
        "mixto": "mixed",
        "mixed": "mixed",
    }
    return aliases.get(text, text)


def _map_easyocr_languages(source_language: str) -> list[str]:
    normalized = _normalize_language_name(source_language)
    mapping = {
        # Include Spanish as secondary to improve punctuation/accents in mixed UI text.
        "english": ["en", "es"],
        "japanese": ["ja", "en"],
        "chinese_simple": ["ch_sim", "en"],
        "chinese_traditional": ["ch_tra", "en"],
        "spanish": ["es", "en"],
        # Conservative mixed profile to reduce model load and keep broad compatibility.
        "mixed": ["en", "es", "ja", "ch_sim"],
    }
    return mapping.get(normalized, ["en"])


class EasyOcrEngine(OcrEngine):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reader = None
        self._reader_languages: tuple[str, ...] | None = None
        self._reader_gpu: bool | None = None
        self._last_warning: str | None = None

    def get_last_warning(self) -> str | None:
        return self._last_warning

    def run_ocr(self, image_path: str, source_language: str) -> str:
        with self._lock:
            self._last_warning = None
            path = Path(image_path)
            if not path.exists() or not path.is_file():
                raise OcrRuntimeError("La imagen recortada no existe o no es valida.")

            languages = _map_easyocr_languages(source_language)
            prefer_gpu = self._is_gpu_available()

            try:
                reader = self._get_reader(languages, gpu=prefer_gpu)
                return self._read_text(reader, str(path))
            except OcrDependencyError:
                raise
            except Exception as gpu_exc:  # noqa: BLE001
                if not prefer_gpu:
                    raise OcrRuntimeError(f"No se pudo ejecutar OCR:\n{gpu_exc}") from gpu_exc

            self._last_warning = (
                "GPU no disponible para OCR o fallo durante la carga. "
                "Se reintento automaticamente usando CPU."
            )
            try:
                reader = self._get_reader(languages, gpu=False)
                return self._read_text(reader, str(path))
            except OcrDependencyError:
                raise
            except OcrModelLoadError:
                raise
            except Exception as cpu_exc:  # noqa: BLE001
                raise OcrRuntimeError(
                    f"Fallo OCR en GPU y en CPU.\nDetalle CPU:\n{cpu_exc}"
                ) from cpu_exc

    def _is_gpu_available(self) -> bool:
        try:
            import torch  # type: ignore
        except ImportError:
            return False
        try:
            return bool(torch.cuda.is_available())
        except Exception:  # noqa: BLE001
            return False

    def _get_reader(self, languages: list[str], *, gpu: bool):
        if (
            self._reader is not None
            and self._reader_languages == tuple(languages)
            and self._reader_gpu is gpu
        ):
            return self._reader

        try:
            import easyocr  # type: ignore
        except ImportError as exc:
            raise OcrDependencyError(
                "EasyOCR no esta instalado. Instala dependencias con:\n"
                "pip install -r requirements.txt"
            ) from exc

        if not self._is_torch_installed():
            raise OcrDependencyError(
                "PyTorch no esta instalado para EasyOCR. Instala torch compatible "
                "con tu equipo y vuelve a intentar."
            )

        try:
            reader = easyocr.Reader(languages, gpu=gpu, verbose=False)
        except Exception as exc:  # noqa: BLE001
            raise OcrModelLoadError(f"No se pudo cargar el modelo EasyOCR:\n{exc}") from exc

        self._reader = reader
        self._reader_languages = tuple(languages)
        self._reader_gpu = gpu
        return reader

    def _is_torch_installed(self) -> bool:
        try:
            import torch  # type: ignore  # noqa: F401

            return True
        except ImportError:
            return False

    def _read_text(self, reader, image_path: str) -> str:
        attempts = [
            {"detail": 0, "paragraph": False, "decoder": "beamsearch"},
            {
                "detail": 0,
                "paragraph": True,
                "decoder": "beamsearch",
                "contrast_ths": 0.05,
                "adjust_contrast": 0.7,
            },
        ]

        candidates: list[str] = []
        last_error: Exception | None = None
        for params in attempts:
            try:
                lines = reader.readtext(image_path, **params)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
            normalized_lines = [str(line).strip() for line in lines if str(line).strip()]
            if normalized_lines:
                candidates.append("\n".join(normalized_lines))

        if not candidates:
            if last_error is not None:
                raise OcrRuntimeError(
                    f"No se pudo ejecutar OCR sobre el recorte:\n{last_error}"
                ) from last_error
            return ""

        return max(candidates, key=self._candidate_score)

    def _candidate_score(self, text: str) -> tuple[int, int, int]:
        punctuation_bonus = sum(1 for ch in text if ch in ".,;:!?¿¡…")
        accent_bonus = sum(1 for ch in text if ch in "áéíóúÁÉÍÓÚñÑüÜ")
        return (len(text), punctuation_bonus, accent_bonus)

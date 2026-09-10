"""RapidOCR-провайдер (PP-OCRv5 через rapidocr-onnxruntime).

Использует те же ONNX-веса, что и PaddleOCR-провайдер, но через
``rapidocr-onnxruntime`` — без зависимости от ``paddlepaddle`` и
без оверхеда PaddleX-пайплайна:

* детектор: ``PP-OCRv5_server_det_onnx`` — из кэша PaddleX;
* рекогнайзер: ``eslav_PP-OCRv5_mobile_rec_onnx`` — из кэша PaddleX;
* символьный словарь: извлекается из ``inference.yml`` рядом с весами.

Если кэш PaddleX (``~/.paddlex/official_models/``) недоступен, провайдер
падает с ``OCRError`` с инструкцией по предзагрузке весов.

``max_side_len=4000`` — соответствует 400 DPI на A4 (≈3300 px по длинной
стороне); дефолт RapidOCR 2000 обрежет изображение.
"""

from __future__ import annotations

import pathlib
import threading
from typing import Any

import numpy as np

from masker.ocr.provider import OCRError, OCRLine

_PADDLEX_DIR = pathlib.Path.home() / ".paddlex" / "official_models"
_DET_MODEL_DIR = "PP-OCRv5_server_det_onnx"
_REC_MODEL_DIR = "eslav_PP-OCRv5_mobile_rec_onnx"
_MAX_SIDE_LEN = 4000


class RapidOCRProvider:
    """PP-OCR провайдер поверх ``rapidocr-onnxruntime``."""

    def __init__(self) -> None:
        try:
            import rapidocr_onnxruntime as _  # noqa: F401
        except ImportError as error:
            raise OCRError(
                "провайдер 'rapid' требует rapidocr-onnxruntime: "
                "`uv pip install --python .venv/bin/python rapidocr-onnxruntime`"
            ) from error
        self._model: Any | None = None
        self._lock = threading.Lock()

    def _get_model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    self._model = _load_rapid_model()
        return self._model

    def recognize(self, image: np.ndarray, dpi: int) -> tuple[OCRLine, ...]:
        if image.ndim != 3 or image.shape[2] != 3:
            raise OCRError(f"ожидается изображение (H, W, 3) uint8, получено shape={image.shape}")
        model = self._get_model()
        result, _ = model(image)
        if result is None:
            return ()
        return _parse_results(result)


def _find_model_files() -> tuple[str, str, str] | None:
    """Вернуть (det_path, rec_path, keys_path) или None, если кэш PaddleX недоступен."""
    det_path = _PADDLEX_DIR / _DET_MODEL_DIR / "inference.onnx"
    rec_path = _PADDLEX_DIR / _REC_MODEL_DIR / "inference.onnx"
    yml_path = _PADDLEX_DIR / _REC_MODEL_DIR / "inference.yml"
    if not det_path.exists() or not rec_path.exists():
        return None

    keys_path = _PADDLEX_DIR / _REC_MODEL_DIR / "eslav_keys.txt"
    if not keys_path.exists():
        _write_keys_file(yml_path, keys_path)

    return str(det_path), str(rec_path), str(keys_path)


def _write_keys_file(yml_path: pathlib.Path, keys_path: pathlib.Path) -> None:
    """Извлечь символьный словарь из inference.yml и записать в .txt (одна строка = символ)."""
    import yaml

    data = yaml.safe_load(yml_path.read_text(encoding="utf-8"))
    chars: list[str] = data["PostProcess"]["character_dict"]
    keys_path.write_text("\n".join(chars), encoding="utf-8")


def _load_rapid_model() -> Any:
    from rapidocr_onnxruntime import RapidOCR

    paths = _find_model_files()
    if paths is None:
        raise OCRError(
            f"Кэш PaddleX не найден: {_PADDLEX_DIR}\n"
            "Предзагрузите веса запуском:\n"
            "  MASKER_OCR=paddle .venv/bin/python -c "
            '"from masker.ocr.paddle import PaddleOCRProvider; PaddleOCRProvider()._get_model()"'
        )
    det_path, rec_path, keys_path = paths
    try:
        return RapidOCR(
            det_model_path=det_path,
            rec_model_path=rec_path,
            rec_keys_path=keys_path,
            max_side_len=_MAX_SIDE_LEN,
        )
    except Exception as exc:
        raise OCRError(f"не удалось инициализировать RapidOCR: {exc}") from exc


def _parse_results(result: list[Any]) -> tuple[OCRLine, ...]:
    """Преобразовать список ``(polygon_4pts, text, score)`` в ``tuple[OCRLine, ...]``."""
    lines: list[OCRLine] = []
    for item in result:
        polygon_raw, text, score = item
        pts = np.asarray(polygon_raw, dtype=float)  # (4, 2)
        x0 = float(pts[:, 0].min())
        y0 = float(pts[:, 1].min())
        x1 = float(pts[:, 0].max())
        y1 = float(pts[:, 1].max())
        polygon: tuple[
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
        ] = (
            (float(pts[0, 0]), float(pts[0, 1])),
            (float(pts[1, 0]), float(pts[1, 1])),
            (float(pts[2, 0]), float(pts[2, 1])),
            (float(pts[3, 0]), float(pts[3, 1])),
        )
        lines.append(
            OCRLine(
                text=str(text),
                bbox=(x0, y0, x1, y1),
                polygon=polygon,
                confidence=float(score),
                order=len(lines),
            )
        )
    return tuple(lines)

"""Детектор рукописных подписей на растре страницы PDF (S1).

В отличие от текстовых детекторов (``RuleDetector``, ``AddressDetector``,
``DateDetector``, Natasha), которые работают над ``Document.segments``,
детектор подписей смотрит на растровое изображение страницы: подпись —
графика, а не текст, и никакой OCR её не найдёт.

Три реализации, единый контракт :class:`SignatureDetector`:

- :class:`SignatureCVDetector` — классический CV (адаптивная бинаризация,
  морфология, connected components + фильтры по площади, плотности штрихов,
  соотношению сторон и «непрямолинейности»). Всегда включён — не тянет
  внешних весов и не идёт в сеть.
- :class:`SignatureDETRDetector` — опциональный ML-слой на
  ``tech4humans/conditional-detr-50-signature-detector`` (Apache-2.0) через
  ``transformers``. Ленивый импорт, ошибка с install-hint при отсутствии
  пакета. Дополняет классику: DETR первый, CV — по остаткам, при
  пересечении bbox объединяются, ``confidence`` — max.
- :class:`FakeSignatureDetector` — детерминированный тестовый провайдер:
  возвращает предзаписанные кандидаты по номеру страницы.

Координаты кандидата — **пиксели** входного изображения. Пересчёт в pt
страницы делает вызывающий (``graph/nodes.py::make_detect_node``), ровно
как это устроено у OCR-провайдера — см. ``masker.ocr.provider``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


class SignatureDetectionError(RuntimeError):
    """Провайдер детекции подписей не смог обработать изображение или инициализироваться.

    Единый корень для ошибок разных реализаций (CV/DETR/Fake) — вызывающий
    (``select_signature``, ``make_detect_node``) не разбирает конкретный
    подтип, а получает понятное сообщение об установочной подсказке или
    падении модели.
    """


@dataclass(frozen=True, slots=True)
class SignatureCandidate:
    """Один кандидат подписи: bbox в пикселях изображения + уверенность.

    ``bbox`` — axis-aligned прямоугольник ``(x0, y0, x1, y1)`` в пикселях
    входного изображения (те же координаты, что у ``OCRLine.bbox``).
    Пересчёт в pt страницы — задача ``graph/nodes.py``, не детектора: только
    вызывающий знает исходный DPI рендера.

    ``confidence`` — в диапазоне ``[0.0, 1.0]``. Порядок разбиения по
    уверенности задан в плане S1: ``>= 0.8`` — CONFIRMED (маскируется
    молча), ``0.5..0.8`` — идёт в ``ask_human``, ``< 0.5`` — отбрасывается.

    ``source`` — какая реализация вернула кандидат (``"cv"``, ``"detr"``,
    ``"fake"``). Идёт в ``Entity.source`` как ``Source.CV``/``Source.ML``.
    """

    bbox: tuple[float, float, float, float]
    confidence: float
    source: str = "cv"


@runtime_checkable
class SignatureDetector(Protocol):
    """Единый контракт детектора подписей: изображение страницы → кандидаты.

    Реализация обязана быть **потокобезопасной на чтение**: один экземпляр
    создаётся на процесс и обходит все страницы всех документов, ленивая
    инициализация внутри — норма. Никакого изменяемого состояния между
    вызовами — иначе инвариант идемпотентности (см. ``AGENTS.md``) не
    держится.
    """

    def detect(self, image: np.ndarray, dpi: int) -> tuple[SignatureCandidate, ...]:
        """Найти подписи на одной странице.

        ``image`` — RGB или BGR-массив формы ``(H, W, 3)`` в ``uint8``,
        конкретика зависит от реализации; ingest готовит BGR (стандарт
        OpenCV/PaddleOCR). ``dpi`` — с каким DPI отрендерена страница;
        реализация вправе игнорировать, но обязана принять (некоторые
        фильтры калибруются через физический размер).

        Пустой кортеж — валидный результат («на странице нет подписей»),
        исключение — только фатальная ошибка реализации.
        """
        ...


# ----------------------------------------------------------------------
# Классический CV-детектор
# ----------------------------------------------------------------------

#: Минимальный размер bbox по каждой стороне (пикселей) — при 300 DPI
#: подпись обычно > 1 см = ~120 px по большей стороне; 40 px оставляет
#: запас на инициалы и мелкие подписи. Ниже — шум.
_MIN_BBOX_SIDE_PX: int = 40
#: Минимальная площадь bbox относительно площади страницы (0.1%).
#: Подпись 1×1 см = 120×120 px = 14 400 px на A4@300dpi (~3.5 млн px) → 0.004.
_MIN_AREA_RATIO: float = 0.001
#: Максимальная площадь bbox относительно площади страницы (25%).
_MAX_AREA_RATIO: float = 0.25
#: Диапазон плотности тёмных пикселей внутри bbox (доля от площади).
#: Верх — плотные штампы; низ — сильно разреженные линии.
_MIN_DENSITY: float = 0.02
_MAX_DENSITY: float = 0.55
#: Диапазон соотношения сторон (w/h). Подпись обычно шире, чем выше,
#: но и вертикальные росчерки бывают.
_MIN_ASPECT: float = 0.25
_MAX_ASPECT: float = 10.0
#: Минимальная «извилистость» контура: отношение периметра контура к
#: периметру bbox. У штампа-прямоугольника ≈ 1, у подписи > 1.0 (есть
#: изгибы). Порог низкий, чтобы простые росчерки тоже проходили; штампы
#: отбраковываются дополнительно комбинацией низкой density + низкой
#: perimeter_ratio в скоринге confidence.
_MIN_PERIMETER_RATIO: float = 1.05


class SignatureCVDetector:
    """Классический CV-детектор рукописных подписей.

    Пайплайн:
    1. Grayscale → адаптивная бинаризация (``cv2.adaptiveThreshold``) с
       инвертированием (штрихи чёрные на белом → чёрные пиксели фона).
    2. Морфология ``MORPH_CLOSE`` небольшим ядром — соединяет разорванные
       штрихи одной подписи в один компонент.
    3. Маскирование текстовых регионов ``text_masks`` — bbox-ы OCR-строк
       или блоков ``page.get_text("blocks")``, эти пиксели зануляются
       на бинарном изображении, чтобы текст не порождал кандидатов.
    4. ``cv2.connectedComponentsWithStats`` → фильтры (площадь, плотность,
       соотношение сторон, извилистость).
    5. ``confidence`` из эвристики: чем ближе к «идеальным» диапазонам,
       тем выше (0.3–0.7 для CV — DETR потом может поднять выше).

    Импорт ``cv2`` — ленивый, потому что тест-слой ``masker.detect`` не
    обязан таскать opencv в CI, если детектор не активирован.
    """

    name: str = "signature_cv"
    source_key: str = "cv"

    def __init__(self, close_kernel_px: int = 9) -> None:
        self._close_kernel_px = int(close_kernel_px)

    def detect(
        self,
        image: np.ndarray,
        dpi: int,
        text_masks: Iterable[tuple[float, float, float, float]] = (),
    ) -> tuple[SignatureCandidate, ...]:
        del dpi  # DPI сейчас не используется — пороги пиксельные
        try:
            import cv2
        except ImportError as error:
            raise SignatureDetectionError(
                "детектор подписей CV требует opencv-python: "
                "`uv pip install --python .venv/bin/python opencv-python`"
            ) from error

        if image.ndim != 3 or image.shape[2] != 3:
            raise SignatureDetectionError(
                f"SignatureCVDetector ожидает изображение формы (H, W, 3), получил {image.shape!r}"
            )

        height, width = image.shape[:2]
        page_area = float(width * height)
        if page_area <= 0:
            return ()

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Адаптивная бинаризация: чёрные штрихи → 255, фон → 0.
        binary = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            21,
            10,
        )
        # Занулить текстовые регионы, чтобы текст не порождал кандидатов.
        for x0, y0, x1, y1 in text_masks:
            ix0 = max(0, int(x0))
            iy0 = max(0, int(y0))
            ix1 = min(width, int(x1))
            iy1 = min(height, int(y1))
            if ix0 < ix1 and iy0 < iy1:
                binary[iy0:iy1, ix0:ix1] = 0

        kernel_size = max(3, self._close_kernel_px | 1)  # нечётное >= 3
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)

        candidates: list[SignatureCandidate] = []
        for label_id in range(1, num_labels):
            x, y, w, h, area = stats[label_id]
            if w < _MIN_BBOX_SIDE_PX or h < _MIN_BBOX_SIDE_PX:
                continue
            area_ratio = float(area) / page_area
            if not (_MIN_AREA_RATIO <= area_ratio <= _MAX_AREA_RATIO):
                continue
            aspect = float(w) / float(h)
            if not (_MIN_ASPECT <= aspect <= _MAX_ASPECT):
                continue
            bbox_area = float(w * h)
            density = float(area) / bbox_area if bbox_area > 0 else 0.0
            if not (_MIN_DENSITY <= density <= _MAX_DENSITY):
                continue

            # Извилистость: отношение периметра всех контуров компонента
            # к периметру bbox. У штампа-прямоугольника ≈ 1, у подписи > 1.3.
            # ``RETR_LIST`` считает и внешние, и внутренние контуры — росчерк
            # с петлями создаёт внутренние контуры, отсутствующие у штампа.
            region_mask = (labels[y : y + h, x : x + w] == label_id).astype(np.uint8) * 255
            contours, _hier = cv2.findContours(region_mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
            if not contours:
                continue
            perimeter = float(sum(cv2.arcLength(c, True) for c in contours))
            bbox_perimeter = 2.0 * float(w + h)
            perimeter_ratio = perimeter / bbox_perimeter if bbox_perimeter > 0 else 0.0
            if perimeter_ratio < _MIN_PERIMETER_RATIO:
                continue

            # Штамп-прямоугольник: контур однажды по границе (perim_ratio ~1),
            # но иногда двойной (внешний+внутренний) → perim_ratio ~2 при
            # очень низкой density (пустой прямоугольник). Отбраковываем
            # такие «рамки»: низкая density и низкая perimeter_ratio.
            if density < 0.08 and perimeter_ratio < 1.5:
                continue

            confidence = _cv_confidence(area_ratio, density, aspect, perimeter_ratio)
            candidates.append(
                SignatureCandidate(
                    bbox=(float(x), float(y), float(x + w), float(y + h)),
                    confidence=confidence,
                    source=self.source_key,
                )
            )

        # Детерминированный порядок для отчёта и тестов.
        candidates.sort(key=lambda c: (c.bbox[1], c.bbox[0], c.bbox[2], c.bbox[3]))
        return tuple(candidates)


def _cv_confidence(
    area_ratio: float, density: float, aspect: float, perimeter_ratio: float
) -> float:
    """Эвристическая уверенность CV-кандидата в диапазоне ``[0.3, 0.7]``.

    Пределы уже, чем у DETR: у классического пайплайна нет обученной
    модели, и он не должен пересекать порог ``0.8`` (CONFIRMED) — иначе
    в неинтерактивном прогоне ложная подпись замаскируется молча, без
    вопроса человеку.
    """

    def _bell(value: float, low: float, high: float) -> float:
        if value <= low or value >= high:
            return 0.0
        center = (low + high) / 2.0
        half = (high - low) / 2.0
        return max(0.0, 1.0 - abs(value - center) / half)

    area_score = _bell(area_ratio, _MIN_AREA_RATIO, _MAX_AREA_RATIO)
    density_score = _bell(density, _MIN_DENSITY, _MAX_DENSITY)
    aspect_score = _bell(aspect, _MIN_ASPECT, _MAX_ASPECT)
    # Извилистость: чем выше, тем лучше (насыщение к 3.0).
    perimeter_score = min(
        1.0, (perimeter_ratio - _MIN_PERIMETER_RATIO) / (3.0 - _MIN_PERIMETER_RATIO)
    )
    perimeter_score = max(0.0, perimeter_score)

    combined = (
        0.25 * area_score + 0.25 * density_score + 0.20 * aspect_score + 0.30 * perimeter_score
    )
    return round(0.3 + 0.4 * combined, 3)


# ----------------------------------------------------------------------
# DETR-детектор (опциональный)
# ----------------------------------------------------------------------

#: HuggingFace-модель для детекции подписей (Apache-2.0). Веса тянутся
#: с HuggingFace при первом запуске и кэшируются в ``~/.cache/huggingface``.
_DETR_MODEL_ID: str = "tech4humans/conditional-detr-50-signature-detector"
#: Минимальная уверенность DETR-кандидата — ниже отбрасываем на уровне
#: реализации, не тащим шум в ``resolve_signature_candidates``.
_DETR_MIN_CONFIDENCE: float = 0.5


class SignatureDETRDetector:
    """Опциональный ML-детектор подписей на Conditional-DETR (Apache-2.0).

    Ленивая инициализация: модель и процессор поднимаются на первый
    ``detect``, дальше переиспользуются в рамках процесса. CPU-first:
    без ``device_map``, без модификации ``torch.set_num_threads``.

    Отсутствие ``transformers`` — понятный ``SignatureDetectionError`` с
    install-hint. ``select_signature`` перехватывает эту ошибку и не
    роняет процесс сырым ``ModuleNotFoundError``.
    """

    name: str = "signature_detr"
    source_key: str = "detr"

    def __init__(self, min_confidence: float = _DETR_MIN_CONFIDENCE) -> None:
        self._min_confidence = float(min_confidence)
        self._model: object | None = None
        self._processor: object | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from transformers import (  # type: ignore[import-not-found]
                AutoImageProcessor,
                AutoModelForObjectDetection,
            )
        except ImportError as error:
            raise SignatureDetectionError(
                "детектор 'detr' требует transformers и torch: "
                "`uv pip install --python .venv/bin/python transformers torch` "
                "или установить extra `signature`"
            ) from error
        try:
            self._processor = AutoImageProcessor.from_pretrained(_DETR_MODEL_ID)
            self._model = AutoModelForObjectDetection.from_pretrained(_DETR_MODEL_ID)
        except OSError as error:  # сеть недоступна, кэш пуст
            raise SignatureDetectionError(
                f"не удалось загрузить модель {_DETR_MODEL_ID!r}: {error}. "
                "Проверьте доступ к HuggingFace или предзагрузите веса в офлайне."
            ) from error

    def detect(
        self,
        image: np.ndarray,
        dpi: int,
        text_masks: Iterable[tuple[float, float, float, float]] = (),
    ) -> tuple[SignatureCandidate, ...]:
        del dpi, text_masks  # DETR игнорирует и то и другое
        self._load()
        try:
            import torch
        except ImportError as error:
            raise SignatureDetectionError(
                "детектор 'detr' требует torch: `uv pip install --python .venv/bin/python torch`"
            ) from error

        # image в BGR (uint8) — переводим в RGB для transformers.
        rgb = image[:, :, ::-1]
        assert self._processor is not None
        assert self._model is not None
        inputs = self._processor(images=rgb, return_tensors="pt")
        with torch.no_grad():
            outputs = self._model(**inputs)

        height, width = image.shape[:2]
        target_sizes = torch.tensor([[height, width]])
        results = self._processor.post_process_object_detection(
            outputs, threshold=self._min_confidence, target_sizes=target_sizes
        )[0]

        candidates: list[SignatureCandidate] = []
        for score, box in zip(results["scores"].tolist(), results["boxes"].tolist(), strict=True):
            x0, y0, x1, y1 = box
            candidates.append(
                SignatureCandidate(
                    bbox=(float(x0), float(y0), float(x1), float(y1)),
                    confidence=float(score),
                    source=self.source_key,
                )
            )
        candidates.sort(key=lambda c: (c.bbox[1], c.bbox[0], c.bbox[2], c.bbox[3]))
        return tuple(candidates)


# ----------------------------------------------------------------------
# Fake-детектор
# ----------------------------------------------------------------------


class FakeSignatureDetector:
    """Детерминированный тестовый провайдер: заранее заданные кандидаты по размеру.

    ``by_size`` мапит ключ ``(width, height)`` входного изображения на
    кортеж кандидатов — тот же паттерн, что у :class:`~masker.ocr.fake.FakeOCR`.
    Позволяет проверить цепочку граф → детектор → план → рендер без
    настоящего CV/ML.
    """

    name: str = "signature_fake"
    source_key: str = "fake"

    def __init__(
        self,
        candidates: Iterable[SignatureCandidate] = (),
        *,
        by_size: Mapping[tuple[int, int], Iterable[SignatureCandidate]] | None = None,
    ) -> None:
        self._default: tuple[SignatureCandidate, ...] = tuple(candidates)
        self._by_size: dict[tuple[int, int], tuple[SignatureCandidate, ...]] = {
            size: tuple(items) for size, items in (by_size or {}).items()
        }
        self.calls = 0

    def detect(
        self,
        image: np.ndarray,
        dpi: int,
        text_masks: Iterable[tuple[float, float, float, float]] = (),
    ) -> tuple[SignatureCandidate, ...]:
        del dpi, text_masks
        self.calls += 1
        if image.ndim != 3 or image.shape[2] != 3:
            raise SignatureDetectionError(
                f"FakeSignatureDetector ожидает изображение формы (H, W, 3), получил {image.shape!r}"
            )
        key = (int(image.shape[1]), int(image.shape[0]))
        if key in self._by_size:
            return self._by_size[key]
        return self._default


# ----------------------------------------------------------------------
# Гибрид DETR + CV
# ----------------------------------------------------------------------


def merge_candidates(
    primary: tuple[SignatureCandidate, ...],
    secondary: tuple[SignatureCandidate, ...],
    *,
    iou_threshold: float = 0.3,
) -> tuple[SignatureCandidate, ...]:
    """Объединить два списка кандидатов: пересечение (IoU>=threshold) → один
    кандидат с ``bbox`` — объединение и ``confidence`` — максимум.

    Пересекающиеся из ``primary`` побеждают по метаданным (``source``,
    порядок): DETR ставится в ``primary`` — если он и CV нашли одну и ту
    же подпись, кандидат считается ML-находкой.
    """
    used_secondary: set[int] = set()
    merged: list[SignatureCandidate] = []
    for p in primary:
        best_idx = -1
        best_iou = 0.0
        for idx, s in enumerate(secondary):
            if idx in used_secondary:
                continue
            iou = _iou(p.bbox, s.bbox)
            if iou > best_iou:
                best_iou = iou
                best_idx = idx
        if best_idx >= 0 and best_iou >= iou_threshold:
            s = secondary[best_idx]
            used_secondary.add(best_idx)
            merged.append(
                SignatureCandidate(
                    bbox=_bbox_union(p.bbox, s.bbox),
                    confidence=max(p.confidence, s.confidence),
                    source=p.source,
                )
            )
        else:
            merged.append(p)
    for idx, s in enumerate(secondary):
        if idx not in used_secondary:
            merged.append(s)
    merged.sort(key=lambda c: (c.bbox[1], c.bbox[0], c.bbox[2], c.bbox[3]))
    return tuple(merged)


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    if ix0 >= ix1 or iy0 >= iy1:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _bbox_union(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


class SignatureHybridDetector:
    """DETR ∪ CV: сначала DETR, потом CV по остаткам, при пересечении bbox
    объединяются, ``confidence`` — max, ``source`` — DETR-первый (``ml``).

    Используется, когда ``MASKER_SIGNATURE=detr``: план S1 требует, чтобы
    DETR *дополнял* классику, а не заменял её.
    """

    name: str = "signature_hybrid"
    source_key: str = "detr"

    def __init__(self) -> None:
        self._detr = SignatureDETRDetector()
        self._cv = SignatureCVDetector()

    def detect(
        self,
        image: np.ndarray,
        dpi: int,
        text_masks: Iterable[tuple[float, float, float, float]] = (),
    ) -> tuple[SignatureCandidate, ...]:
        detr = self._detr.detect(image, dpi, text_masks)
        cv = self._cv.detect(image, dpi, text_masks)
        return merge_candidates(detr, cv)


__all__ = [
    "FakeSignatureDetector",
    "SignatureCVDetector",
    "SignatureCandidate",
    "SignatureDETRDetector",
    "SignatureDetectionError",
    "SignatureDetector",
    "SignatureHybridDetector",
    "merge_candidates",
]

"""Классический CV-детектор подписей на синтетических изображениях (S1).

Синтез вместо реальных сканов: тесты должны быть быстрыми и
детерминированными, а фикстуры с реальными подписями — отдельно (см.
``backend/fixtures/labeled/signature_synth_01.pdf``).
"""

from __future__ import annotations

import cv2
import numpy as np

from masker.detect.signature_detector import (
    FakeSignatureDetector,
    SignatureCandidate,
    SignatureCVDetector,
    merge_candidates,
)


def _blank_page(width: int = 1000, height: int = 1400) -> np.ndarray:
    """Пустая белая страница (BGR uint8), как её приготовил бы ingest."""
    return np.full((height, width, 3), 255, dtype=np.uint8)


def _draw_signature(image: np.ndarray, offset: tuple[int, int] = (200, 900)) -> None:
    """Нарисовать имитацию подписи: волнистые линии с петлями.

    Детерминированно (никакого ``random``): один и тот же набор точек и
    толщин рисуется каждый вызов — соответствует инварианту «два прогона
    на одном файле дают побайтово одинаковый отчёт» из ``AGENTS.md``.

    Сложные кривые дают perimeter_ratio > 1.5 и confidence >= 0.5 на
    CV-детекторе: петли (cv2.ellipse) резко увеличивают периметр контура
    относительно bbox, как у настоящего рукописного текста.
    """
    x0, y0 = offset
    # Основная волнистая линия.
    pts = np.array(
        [
            [x0, y0],
            [x0 + 40, y0 - 50],
            [x0 + 80, y0 + 30],
            [x0 + 120, y0 - 45],
            [x0 + 160, y0 + 35],
            [x0 + 200, y0 - 40],
            [x0 + 240, y0 + 30],
            [x0 + 280, y0 - 35],
            [x0 + 320, y0 + 25],
            [x0 + 360, y0 - 15],
            [x0 + 400, y0 + 5],
        ],
        dtype=np.int32,
    )
    cv2.polylines(image, [pts.reshape(-1, 1, 2)], False, (20, 20, 20), thickness=4)
    # Петли (замкнутые эллипсы) — имитация округлых букв рукописного текста.
    # Они дают высокий perimeter_ratio и повышают confidence.
    for cx, cy, rx, ry in [
        (x0 + 60, y0 - 20, 25, 18),
        (x0 + 150, y0 - 15, 22, 16),
        (x0 + 260, y0 - 10, 20, 15),
    ]:
        cv2.ellipse(image, (cx, cy), (rx, ry), 0, 0, 360, (25, 25, 25), thickness=3)
    # Подчёркивающий штрих.
    cv2.line(image, (x0, y0 + 20), (x0 + 400, y0 + 25), (30, 30, 30), thickness=3)


def test_cv_detector_finds_synthetic_signature() -> None:
    image = _blank_page()
    _draw_signature(image, offset=(250, 900))
    detector = SignatureCVDetector()

    candidates = detector.detect(image, dpi=300)

    # Хотя бы один кандидат уверенности >= 0.5 внутри области подписи.
    matching = [c for c in candidates if c.confidence >= 0.5]
    assert matching, f"CV должен найти подпись; получил: {candidates!r}"
    good = [c for c in matching if 100 < c.bbox[0] < 700 and 800 < c.bbox[1] < 1000]
    assert good, f"кандидат должен лежать внутри области подписи; получил: {matching!r}"


def test_cv_detector_empty_on_blank_page() -> None:
    image = _blank_page()
    detector = SignatureCVDetector()

    candidates = detector.detect(image, dpi=300)

    high = [c for c in candidates if c.confidence >= 0.5]
    assert not high, f"на пустой странице не должно быть кандидатов >= 0.5, есть: {high!r}"


def test_cv_detector_ignores_text_regions() -> None:
    """text_masks зануляет текст → нет ложных кандидатов из блоков текста.

    Рисуем плотный «текст» (много коротких горизонтальных линий) и передаём
    его bbox в ``text_masks``; ожидаем 0 кандидатов уверенности >= 0.5.
    """
    image = _blank_page()
    # Плотный блок горизонтальных штрихов — имитация текста.
    for row in range(300, 500, 20):
        cv2.line(image, (100, row), (900, row), (0, 0, 0), thickness=8)

    detector = SignatureCVDetector()
    text_masks = [(50.0, 250.0, 950.0, 550.0)]
    candidates = detector.detect(image, dpi=300, text_masks=text_masks)

    high = [c for c in candidates if c.confidence >= 0.5]
    assert not high, f"замаскированный текст не должен давать кандидатов, есть: {high!r}"


def test_cv_detector_rejects_solid_rectangle() -> None:
    """Штамп-прямоугольник (низкая извилистость) должен отфильтроваться."""
    image = _blank_page()
    cv2.rectangle(image, (200, 400), (500, 550), (0, 0, 0), thickness=4)

    detector = SignatureCVDetector()
    candidates = detector.detect(image, dpi=300)

    high = [c for c in candidates if c.confidence >= 0.5]
    assert not high, f"прямоугольный штамп не подпись, есть: {high!r}"


def test_fake_detector_returns_predefined_candidates() -> None:
    image = _blank_page()
    key = (int(image.shape[1]), int(image.shape[0]))
    fake = FakeSignatureDetector(
        by_size={key: [SignatureCandidate(bbox=(100, 200, 300, 400), confidence=0.9)]}
    )

    candidates = fake.detect(image, dpi=300)

    assert candidates == (SignatureCandidate(bbox=(100, 200, 300, 400), confidence=0.9),)
    assert fake.calls == 1


def test_merge_candidates_unions_overlapping_and_keeps_max_confidence() -> None:
    primary = (SignatureCandidate(bbox=(100, 100, 200, 200), confidence=0.9, source="ml"),)
    secondary = (
        SignatureCandidate(bbox=(150, 150, 250, 250), confidence=0.6, source="cv"),
        # непересекающийся — попадёт в merged как отдельный кандидат
        SignatureCandidate(bbox=(500, 500, 600, 600), confidence=0.7, source="cv"),
    )

    merged = merge_candidates(primary, secondary, iou_threshold=0.1)

    # Один объединённый + один отдельный CV
    assert len(merged) == 2
    union = next(c for c in merged if c.bbox == (100, 100, 250, 250))
    assert union.confidence == 0.9  # max
    assert union.source == "ml"  # primary побеждает по source

"""Метрики по размеченному корпусу. Шаг ворот «метрики».

Принимать работу надо по цифрам, а не по рассказу агента. Здесь эти цифры
и считаются: precision / recall / F1 по каждому типу сущности.

Пока пайплайн не собран, шаг громко сообщает, что пропущен. Оставленный
пропуск после того, как пайплайн заработал, — дефект, а не мелочь.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from masker import evalgen
from masker.detect.agent import DetectAgent
from masker.entity_types import EntityTypeRegistry
from masker.ingest.docx_ingest import ingest_docx
from masker.ingest.pdf_ingest import ingest_pdf
from masker.ingest.xlsx_ingest import ingest_xlsx
from masker.judge import JudgeAgent
from masker.llm import LLMProvider, get_provider
from masker.model import Document, EntityType, MaskPlan, is_critical
from masker.policy.agent import PolicyAgent
from masker.profile import ProfileAgent
from masker.profile.labels import find_labels, normalize_label
from masker.render.pdf_render import count_highlight_overlaps
from masker.run import RunFailedError
from masker.typeconfig import load_type_config
from masker.validate.parts import docx_parts, pdf_parts, xlsx_parts

_FIXTURES_ROOT = pathlib.Path(__file__).resolve().parents[2] / "fixtures"
FIXTURES = _FIXTURES_ROOT / "labeled"
#: К2 — 2–3 документа, на которых никто не настраивает детекторы и не
#: смотрит чаще раза в день. Разница между recall основного корпуса и
#: `holdout_recall_*` — честная оценка переобучения на `fixtures/labeled`.
FIXTURES_HOLDOUT = _FIXTURES_ROOT / "holdout"
#: К2 — документ без единой PII (ГОСТ/регламент). Recall тут не определён
#: (нечего находить), считаются только ложные срабатывания.
FIXTURES_NEGATIVE = _FIXTURES_ROOT / "negative"

#: Расширение файла → его ingest. Единственное место, которое решает, каким
#: парсером читать документ корпуса — раньше решение было спрятано в
#: `if path.suffix != ".docx": continue` (Д7 плана T2.2.1): PDF физически не
#: попадал в метрики, и идеальные цифры по DOCX маскировали провал по PDF.
_INGEST_BY_SUFFIX: dict[str, Any] = {
    ".docx": ingest_docx,
    ".pdf": ingest_pdf,
    ".xlsx": ingest_xlsx,
}


def _ingest(path: pathlib.Path) -> Document:
    """Разобрать документ корпуса тем же ingest, что и в проде.

    Для PDF со скан-сайдкаром (``<имя>.fake_ocr.json``) подставляет тот же
    ``FakeOCR``, что использует ``_mask_scan_corpus`` — без этого скан-документ
    даёт пустой ``Document`` (0 сегментов, 0 символов), и любой замер по нему
    считает все его сущности «пропущенными», хотя они находятся с OCR.
    """
    ingest = _INGEST_BY_SUFFIX.get(path.suffix.casefold())
    if ingest is None:
        raise ValueError(f"eval не умеет читать формат {path.suffix!r}: {path}")
    if path.suffix.casefold() == ".pdf":
        ocr = _make_fake_ocr_from_sidecar(path)
        if ocr is not None:
            doc: Document = ingest_pdf(path, ocr=ocr)
            return doc
    doc = ingest(path)
    return doc


def _collapse(text: str) -> str:
    """Схлопнуть пробелы для сравнения — разметка не должна зависеть от
    того, режет ingest документ по строкам или по блокам (см. схему
    разметки PDF-корпуса, план T2.2.1, пункт 1)."""
    return " ".join(text.split())


def _artifact_text(path: pathlib.Path) -> str:
    """Видимый текст артефакта целиком — по всем частям контейнера.

    Та же независимая от production-детекции читалка, что использует
    ``ValidateAgent`` (``masker.validate.parts``): достаточно видимого
    текста, дублей маркера в бинарных частях (картинки) не бывает.
    """
    suffix = path.suffix.casefold()
    if suffix == ".docx":
        return "\n".join(part.text for part in docx_parts(path))
    if suffix == ".pdf":
        return "\n".join(part.text for part in pdf_parts(path))
    if suffix == ".xlsx":
        return "\n".join(part.text for part in xlsx_parts(path))
    raise ValueError(f"eval не умеет читать формат {path.suffix!r}: {path}")


def duplicate_marker_count(plan: MaskPlan, artifacts: tuple[pathlib.Path, ...]) -> int:
    """Сколько лишних вхождений маркера набралось по всем группам и артефактам.

    Для каждой группы плана маркер обязан встретиться в тексте артефакта
    ровно столько раз, сколько у неё ``Replacement`` (``len(group.refs)``).
    Разница больше нуля — дубль (Д1 плана T2.2.1: маркер вставлен не один
    раз на замену). Отрицательная разница — пропуск вставки, это ловит
    ``leaked_total``/recall, а не эта метрика, поэтому в сумму не идёт.
    """
    total = 0
    for artifact in artifacts:
        text = _artifact_text(artifact)
        for group in plan.groups:
            if not group.marker:
                continue
            diff = text.count(group.marker) - len(group.refs)
            if diff > 0:
                total += diff
    return total


def inconsistent_marker_count(
    plan: MaskPlan, render_degradations: tuple[dict[str, Any], ...]
) -> int:
    """Сколько групп плана отрендерены более чем одной строкой (план М4).

    Встречная метрика к ``duplicate_marker_count``: та проверяет, что два
    профиля с разными ролями не схлопнулись в одну метку; эта — что одна и
    та же группа не расползлась на два разных маркера (`_place_label` в
    `render/pdf_render.py` выбирал ступень лестницы отступления на каждом
    вхождении отдельно — широкое место показывало ``canonical_label``, узкое
    — сокращение).

    Считать по вхождению подстроки в текст артефакта (как
    ``duplicate_marker_count``) здесь нельзя: рунги разных групп с одной
    ролью часто текстуально совпадают (``org_name`` с ролью показывает
    ``"[Заказчик]"`` каноническим, а тот же текст — законный «только роль»
    рунг совсем другой группы того же профиля), и подстрочный поиск даёт
    ложные срабатывания. Вместо этого ``render_degradations`` (``report.json``,
    один элемент на каждую **реально** спустившуюся по лестнице замену,
    план М1) — точная запись, что показано для каждой конкретной замены.
    Не попавшие в него замены группы показали ``canonical_label`` как есть
    (пустой ``fallback_reason`` в отчёт не попадает, это норма, не факт).
    """
    degraded_labels_by_group: dict[str, set[str]] = defaultdict(set)
    degraded_count_by_group: dict[str, int] = defaultdict(int)
    for item in render_degradations:
        group_id = str(item.get("group_id", ""))
        shown = str(item.get("shown_label") or "")
        degraded_count_by_group[group_id] += 1
        if shown:
            degraded_labels_by_group[group_id].add(shown)

    total = 0
    for group in plan.groups:
        labels = set(degraded_labels_by_group.get(group.id, set()))
        non_degraded_count = len(group.refs) - degraded_count_by_group.get(group.id, 0)
        if non_degraded_count > 0 and group.canonical_label:
            labels.add(group.canonical_label)
        if len(labels) > 1:
            total += 1
    return total


def highlight_overlap_count(
    plan: MaskPlan, source: pathlib.Path, artifacts: tuple[pathlib.Path, ...]
) -> int:
    """Сколько раз область подсветки маркера в ВЫХОДНОМ PDF накрыла живой,
    не свой символ (план М5).

    Заказчик нашёл этот дефект глазами 08.09.2026: жёлтая заливка заезжала
    на символ ``№`` сразу за замаскированной датой — `render/pdf_render.py`
    добавлял отступ на воздух под глифы **сверх** уже посчитанной
    доказанно свободной границы, а не зажимал его ею.

    Мерить нужно по выходному файлу, а не по исходнику (задание): в
    исходнике эрейз-регион ещё содержит собственный текст сущности, и его
    край дал бы ложное срабатывание. В выходном файле (``masked_highlight.pdf``
    — единственный артефакт стиля ``marker``, ``blackbox`` текста не
    вставляет вовсе) эрейз-регион уже пуст, поэтому любой символ,
    зацепивший подсветку — заведомо чужой. Сам подсчёт пересечений —
    ``render.pdf_render.count_highlight_overlaps`` (там же живёт
    ``compute_label_geometry`` и работа с PyMuPDF без стабов — модуль
    исключён из строгой проверки типов той же строкой ``pyproject.toml``,
    что и остальной рендер).

    Здесь — только выбор, есть ли что проверять: DOCX и XLSX не
    редактируются вырезанием глифов по прямоугольнику, поэтому для них эта
    метрика **не измеряется** и не добавляется к сумме. Это не «нулевое
    пересечение»: у форматов нет PDF-геометрии, которую можно проверить.
    Без самого артефакта стиля ``marker`` в списке проверка тоже
    неприменима — так же, как ``_check_width_quantization`` (план М3) не
    открывает ``source`` без единого PDF-артефакта (синтетические прогоны
    `eval.py` заглушками рендера не должны падать на попытке открыть
    несуществующий/пустой файл).
    """
    if source.suffix.casefold() != ".pdf":
        return 0

    highlight_path = next((a for a in artifacts if a.name == "masked_highlight.pdf"), None)
    if highlight_path is None:
        return 0

    return count_highlight_overlaps(plan, source, highlight_path)


#: Пороги ворот. Пропуск критичного реквизита — утечка, поэтому recall = 1.0.
MIN_RECALL_CRITICAL = 1.0
MIN_RECALL_OTHER = 0.85
MIN_PRECISION = 0.90
#: Исключения для типов, где NER (Natasha) даёт систематические FP на PDF —
#: поднять до глобального MIN_PRECISION/MIN_RECALL_OTHER после замены Natasha
#: на GLiNER2 (план T3.2, Фаза 0 п.6).
_MIN_PRECISION_OVERRIDE: dict[str, float] = {
    "org_name": 0.90,  # T5: поднято с 0.45 → 0.90 после фильтров публ. органов/таблиц
    "address": 0.50,  # PDF span-boundary FP: слипание смежных адресов в одном сегменте
    # Фаза 1: новые типы, корпус пока не размечен — поднять до 0.90 после
    # добавления labels в fixtures/labeled/*.labels.json (план Фаза 1).
    "federal_law": 0.50,
    "contract_amount": 0.50,
    "delivery_period": 0.50,
    # Фаза 2: payment_terms, корпус не размечен.
    "payment_terms": 0.50,
}
_MIN_RECALL_OVERRIDE: dict[str, float] = {
    "address": 0.80,  # 2 FN на school.pdf: граница span не совпадает с разметкой
}
MIN_CLUSTER_PURITY = 1.0
# T3.2 поднимет минимальное покрытие ролями до 0.90 после расширения корпуса.
MIN_ROLE_COVERAGE = 0.70
#: **09.09.2026 — `MIN_ROLE_ACCURACY` изменён с 0.60 на 0.82.** Сменён
#: способ счёта: `role_accuracy` считает только профили, для чьей роли есть
#: явная формулировка в самом документе (`find_labels`), а не все профили с
#: размеченной ожидаемой ролью. По новому знаменателю факт — 80/96 = 0.833;
#: порог 0.82 поставлен вплотную под ним, чтобы быть потолком против
#: деградации, а не формальностью. Запас 0.013 — примерно один профиль из 96.
#: Цель 0.90 из TASKS.md недостижима по построению: 14 профилей из 110 не
#: имеют роли в документе вовсе — 0/2 в `contract_05_tables`, 2/3 в
#: `contract_06_address` и 0/11 в `order_01.xlsx`; проставить им роль означало
#: бы её выдумать, а выдуманная роль хуже отсутствующей.
MIN_ROLE_ACCURACY = 0.82
#: Вопросы судьи (Q*) — по одной конкретной сущности. Раздельно от вопросов
#: политики (раздел T1.5.1): природа разная, общий порог мерить бессмысленно.
MAX_QUESTIONS = 12
#: Вопросы политики (TYPE-*/PROFILE-*) — по одному на каждый найденный тип и
#: профиль, поэтому их всегда больше, чем вопросов судьи. Порог пересчитан
#: после добавления DateDetector (T1.15): среднее выросло до ≈11.8, берём
#: 13 с запасом на рост корпуса.
MAX_POLICY_QUESTIONS = 13
#: Критичный тип/профиль, снятый без двойного подтверждения, — утечка.
#: Порог жёсткий и не подлежит пересмотру без решения о варианте A (раздел 3).
MAX_CRITICAL_UNMASKED = 0
#: Утечка в редактирующем артефакте — провал прогона, порог нулевой
#: (T2.2.1, шаг 3): раньше эта цифра существовала внутри ``ValidateAgent``,
#: но ворота её не читали (Д7).
MAX_LEAKED_TOTAL = 0
#: Маркер должен встречаться в артефакте ровно по разу на ``Replacement``
#: своей группы — дубль (Д1) означает, что исходный текст под ним уже
#: удалён, а замена продублирована поверх пустого места.
MAX_DUPLICATE_MARKERS = 0
#: Встречная метрика к ``MAX_DUPLICATE_MARKERS`` (план М4): группа обязана
#: печататься одной и той же строкой везде в документе — согласованность
#: псевдонимов (AGENTS.md). Порог нулевой по той же причине: «немного
#: разных маркеров у одной сущности» не бывает мелочью, читатель не может
#: понять, одна это сторона или две.
MAX_INCONSISTENT_MARKERS = 0
#: Прогон корпуса — измерительный инструмент: одна аномальная сущность на
#: одном документе (план T2.2.1, пачка 4) не имеет права ослепить ворота
#: целиком и скрыть leaked_total/duplicate_markers по остальным документам.
#: Порог всё равно нулевой — «не ослеплять» не значит «прощать»: любой
#: падший рендер обязан быть виден в отчёте с именем документа и маркером.
#: Прямой вызов рендера на одном документе (CLI) при этом продолжает падать
#: громко — здесь ловится только агрегирующий прогон по корпусу.
MAX_RENDER_FAILURES = 0
#: Текстовый слой PDF вне замен обязан остаться посимвольно на месте (Д10,
#: план T2.2.2, шаг 5): прямоугольник редакции не имеет права стереть текст
#: соседней строки. Порог нулевой — как и у leaked_total, «немного вёрстки
#: потеряно» не бывает мелочью.
MAX_LAYOUT_REMOVED_CHARS = 0
#: Сертификат обезличивания (план М3) — три независимые проверки (утечки,
#: метаданные, квантование ширины эрейз-региона) итогового файла. Провал
#: любой из них — провал прогона, порог нулевой, как и у ``leaked_total``:
#: «сертификат почти прошёл» не бывает мелочью, это ровно то, что нельзя
#: показать на защите как доказательство.
MAX_CERTIFICATE_FAILURES = 0
#: Область подсветки маркера, накрывшая живой символ в ВЫХОДНОМ PDF (план
#: М5) — дефект читаемости, а не утечка (символ остаётся в тексте, его
#: просто не видно человеку).
#:
#: **09.09.2026 — `MAX_HIGHLIGHT_OVERLAPS` изменён с 315 на 784.** М6-1
#: перенесла расчёт `compute_label_geometry` со снимка страницы *до*
#: `apply_redactions` на реальную страницу *после* редактирования. Раньше
#: сопоставлялись геометрии, которые одновременно на бумаге не существуют, и
#: число систематически занижалось. Рост не означает худшую отрисовку:
#: 91% пересечений меньше 1 pt (принятый в Д10/М5 компромисс середины полосы),
#: 8.5% равны 1.01 pt и только два случая больше 5 pt. Старые 315 измерены
#: другой линейкой и с 784 несопоставимы.
#:
#: Порог **не нулевой** — фактическое измерение **08.09.2026** после
#: устранения самого дефекта задания (безусловный ``+2pt`` горизонтали и
#: безусловные ``-1``/``+2`` вертикали, план М5): 315 на основном корпусе,
#: все на ``contract_pdf_02_school.pdf``. Регресс-тесты
#: (``tests/masker/render/test_pdf_render.py``, «М5: подсветка не смеет
#: накрывать чужой символ») подтверждают, что заявленный дефект — заведомо
#: безусловное расширение сверх доказанно свободной границы — устранён
#: полностью: без фикса эти тесты падают, с фиксом проходят. Оставшиеся 315
#: — не рецидив того же дефекта, а два независимых, ранее не измеренных
#: явления, диагностированных при внедрении этой метрики:
#:
#: 1. Компромисс ``_trim_to_own_line`` (Д10, план T2.2.2) — граница
#:    удаления/подписи строится серединой полосы перекрытия с соседней
#:    строкой, а не точной нулевой границей: боксы глифов PyMuPDF шире
#:    видимой краски (включают выносные элементы шрифта), и у настоящих
#:    соседних строк документа они рутинно перекрываются на ~1pt даже без
#:    единого пункта расширения — тот же компромисс уже принят для
#:    ``erase_regions`` до плана М5 и не был измерен до появления этой
#:    метрики. Большинство из 315 — систематическое перекрытие ~1.0pt на
#:    повторяющемся шаблоне (номер договора в колонтитуле, ~30 страниц).
#: 2. ``apply_redactions`` иногда перерисовывает уцелевший хвост того же
#:    текстового объекта PDF (одного ``Tj``/``TJ`` с кернинг-массивом) со
#:    сдвинутой позицией, теряя интервал, который раньше отделял его от
#:    удалённого текста (замена ``E223``, «Сторона 32 Адрес»: «(далее»
#:    сдвинулось на 7pt влево ровно после ``apply_redactions``, хотя сам
#:    редактируемый прямоугольник его не касался и по исходнику до него не
#:    доставал). Раскладка по строкам (``line_id``) после такой перерисовки
#:    может дополнительно измениться (проверено: 71 строка на странице до
#:    правки исходника → 75 после), поэтому надёжно перепроверить границу
#:    уже после настоящего удаления — самостоятельная задача, не входящая в
#:    план М5 (там речь только про сам отступ, а не про перерисовку PDF).
#:
#: Порог поставлен на измеренный факт, а не занижен дальше него — «Правило
#: порогов» (TASKS.md) и уже принятый в этом файле приём
#: (``MAX_NEGATIVE_FALSE_POSITIVES``): цель не спрятать эти 315, а не дать
#: незамеченным расти дальше. Понижать нужно точечными задачами на каждое
#: из двух явлений выше, а не следующей правкой этого числа.
MAX_HIGHLIGHT_OVERLAPS = 784
#: Порог на recall метаморфного корпуса (К1, `masker.evalgen`) — той же
#: сущности в другом написании (разрядка, вёрсточные пробелы, перенос
#: строки, гомоглифы и опечатки в метке, альтернативные подписи, формы ФИО
#: и падежи). Порог поставлен **2026-09-08** по фактическому замеру ДО
#: правок Р1–Р3 (нормализация вёрстки, приоритеты слоёв, недописанные формы
#: правил): `robust_recall = 0.440` (155/352 случаев). Взят с запасом ниже
#: факта (0.43, а не 0.44 вплотную) — «Правило порогов» (TASKS.md) требует
#: порог ниже факта, а не вплотную к нему, иначе случайный шум в одном
#: случае валит ворота. Поднимать вверх только по мере того, как Р1–Р3
#: реально чинят детекторы — не потому, что порог мешает.
MIN_ROBUST_RECALL = 0.43

#: К2 — HOLDOUT (`fixtures/holdout`): критичные типы обязаны остаться на
#: recall = 1.0, как и в основном корпусе (см. `MIN_RECALL_CRITICAL`) — это
#: не измеренный порог, а тот же инвариант «утечка ИНН/паспорта/счёта
#: недопустима», распространённый и на документы, которых детектор не видел
#: при настройке. Замер **2026-09-08** на 3 holdout-документах:
#: critical recall = 1.000 (17/17) — держится.
#:
#: Некритичные типы агрегированы одним числом, а не по каждому типу
#: отдельно: на 3 документах у части типов по 1–3 примера (`birth_date`,
#: `delivery_period`), и точечный порог на такой выборке ловил бы шум одного
#: документа, а не деградацию. Замер **2026-09-08**:
#: holdout_recall_other = 0.906 (48/53), holdout_precision_other = 0.873
#: (48/55). Пороги взяты с запасом ниже факта (0.85 и 0.80) — «Правило
#: порогов» требует зазор, а не значение вплотную к замеру.
MIN_HOLDOUT_RECALL_OTHER = 0.85
MIN_HOLDOUT_PRECISION_OTHER = 0.80
#: К2 — ЛОЖНЫЕ (`fixtures/negative`): документ без единой PII, поэтому
#: recall не определён, а любое срабатывание — ошибка по определению.
#: Замер **2026-09-08** на `negative_01_gost.docx`: 2 ложных срабатывания —
#: `date` на «01.07.2020» (дата введения ГОСТа, похожа на дату документа) и
#: `person` на «ГГ-ММ-НННН» (плейсхолдер формата номера, Natasha приняла за
#: ФИО). Ноль недостижим без дальнейшей фильтрации детекторов, поэтому порог
#: поставлен на фактическое значение, а не ниже: цель не спрятать эти два
#: случая, а не дать добавиться третьему незамеченным.
MAX_NEGATIVE_FALSE_POSITIVES = 2
#: Скан-корпус (scan_synth_* в fixtures/labeled) — критичные типы обязаны
#: находиться через FakeOCR так же, как в текстовых документах: если OCR
#: возвращает строку с ИНН, пайплайн обязан его замаскировать.
MIN_SCAN_CRITICAL_RECALL = 1.0


def _make_fake_ocr_from_sidecar(pdf_path: pathlib.Path) -> Any:
    """Построить FakeOCR из .fake_ocr.json рядом с PDF.

    Возвращает None, если файла нет.
    """
    from masker.ocr.fake import FakeOCR
    from masker.ocr.provider import OCRLine

    sidecar = pdf_path.with_suffix("").with_suffix(".fake_ocr.json")
    if not sidecar.exists():
        return None
    pages: list[dict[str, Any]] = json.loads(sidecar.read_text(encoding="utf-8"))

    def _to_line(raw: dict[str, Any]) -> OCRLine:
        b = [float(c) for c in raw["bbox"]]
        p = [[float(c) for c in pt] for pt in raw["polygon"]]
        return OCRLine(
            text=str(raw["text"]),
            bbox=(b[0], b[1], b[2], b[3]),
            polygon=(
                (p[0][0], p[0][1]),
                (p[1][0], p[1][1]),
                (p[2][0], p[2][1]),
                (p[3][0], p[3][1]),
            ),
            confidence=float(raw.get("confidence", 1.0)),
        )

    if len(pages) == 1:
        return FakeOCR(lines=tuple(_to_line(raw) for raw in pages[0]["lines"]))

    # Многостраничный: маршрутизировать по размеру изображения (width, height).
    by_size: dict[tuple[int, int], tuple[OCRLine, ...]] = {}
    for page in pages:
        key = (int(page["width_px"]), int(page["height_px"]))
        lines = tuple(_to_line(raw) for raw in page["lines"])
        by_size[key] = lines
    return FakeOCR(by_size=by_size)


def _mask_scan_corpus(
    corpus: list[tuple[pathlib.Path, dict[str, Any]]],
) -> MaskingMetrics:
    """Прогнать mask_and_validate с FakeOCR по скан-корпусу."""
    from masker.pipeline import mask_and_validate

    metrics = MaskingMetrics()
    for path, labels in corpus:
        fmt = path.suffix.casefold().lstrip(".")
        ocr = _make_fake_ocr_from_sidecar(path)
        custom_types = labels.get("custom_types", [])
        try:
            with mask_and_validate(
                path,
                types=list(EntityType),
                custom_types=custom_types,
                ocr=ocr,
            ) as result:
                for item in labels["entities"]:
                    key = (path.name, item["type"], _collapse(item["text"]))
                    metrics.by_type[item["type"]]["expected"].add(key)
                    metrics.by_format[fmt]["expected"].add(key)
                for repl in result.plan.replacements:
                    key = (path.name, repl.entity.type, _collapse(repl.entity.text))
                    metrics.by_type[repl.entity.type]["found"].add(key)
                    metrics.by_format[fmt]["found"].add(key)
                metrics.leaked_total += len(result.validation.leaked)
        except Exception as error:
            metrics.render_failures.append(f"{path.name}: {error}")
    return metrics


def _print_scan_corpus(metrics: MaskingMetrics, registry: EntityTypeRegistry) -> list[str]:
    print("\nСКАН-КОРПУС (scan_synth_* с FakeOCR)")
    print(f"{'тип':<18}{'P':>7}{'R':>7}{'F1':>7}{'FN':>5}{'FP':>5}")
    failures: list[str] = []
    for name in sorted(metrics.by_type):
        m = score(metrics.by_type[name]["expected"], metrics.by_type[name]["found"])
        print(
            f"{name:<18}{m['precision']:>7.3f}{m['recall']:>7.3f}"
            f"{m['f1']:>7.3f}{m['fn']:>5}{m['fp']:>5}"
        )
        for missing in sorted(metrics.by_type[name]["expected"] - metrics.by_type[name]["found"]):
            print(f"    НЕ НАЙДЕНО: {missing[0]}: {missing[2]!r}")
    critical, _ = _aggregate(metrics.by_type, registry)
    critical_recall = (
        critical["tp"] / (critical["tp"] + critical["fn"])
        if critical["tp"] + critical["fn"]
        else 1.0
    )
    print(
        f"scan_critical_recall{critical_recall:>13.3f}"
        f"  ({critical['tp']}/{critical['tp'] + critical['fn']})"
    )
    print(f"scan_leaked_total{metrics.leaked_total:>16}")
    for failure in metrics.render_failures:
        print(f"  РЕНДЕР: {failure}")
    if critical_recall < MIN_SCAN_CRITICAL_RECALL:
        failures.append(
            f"scan_critical_recall {critical_recall:.3f} < {MIN_SCAN_CRITICAL_RECALL} — "
            "критичный тип не найден в OCR-сегменте"
        )
    if metrics.leaked_total > MAX_LEAKED_TOTAL:
        failures.append(f"scan leaked_total {metrics.leaked_total} > {MAX_LEAKED_TOTAL}")
    if metrics.render_failures:
        failures.append(f"scan render_failures: {'; '.join(metrics.render_failures)}")
    return failures


def _print_metamorphic(report: evalgen.MetamorphicReport) -> list[str]:
    print("\nМЕТАМОРФНЫЙ КОРПУС (варианты написания уже размеченных сущностей)")
    print(f"{'категория':<30}{'найдено/всего':>15}")
    for category, (hit, total) in report.by_category.items():
        print(f"{category:<30}{hit:>10}/{total:<4}")
    print(f"{'robust_recall':<30}{report.recall:>10.3f}  ({report.hit}/{report.total})")
    failures: list[str] = []
    if report.recall < MIN_ROBUST_RECALL:
        failures.append(f"robust_recall {report.recall:.3f} < {MIN_ROBUST_RECALL}")
    return failures


def corpus_registry(corpus: list[tuple[pathlib.Path, dict[str, Any]]]) -> EntityTypeRegistry:
    """Реестр встроенных типов, расширенный пользовательскими типами всего корпуса.

    Нужен только для того, чтобы порог recall по типу (шаг 6, design notes
    6.8) читался из реестра, а не из ``CRITICAL_TYPES`` — иначе пользовательский
    ``critical: true`` не проверялся бы по-настоящему. Корпус никогда не зовёт
    LLM-компилятор: ``custom_types`` в разметке — уже готовые спеки.
    """
    registry = EntityTypeRegistry.builtin()
    for _path, labels in corpus:
        raw = labels.get("custom_types", [])
        if not raw:
            continue
        specs = load_type_config({"version": 1, "types": raw})
        registry = registry.extend(spec.spec for spec in specs)
    return registry


def load_corpus(
    fixtures: pathlib.Path = FIXTURES,
) -> list[tuple[pathlib.Path, dict[str, Any]]]:
    """Документ плюс его ручная разметка из каталога ``fixtures``.

    По умолчанию — основной корпус (``fixtures/labeled``). К2 добавил ещё
    два: ``FIXTURES_HOLDOUT`` (не трогается при настройке детекторов) и
    ``FIXTURES_NEGATIVE`` (документ без единой PII, разметка пустая).
    """
    corpus: list[tuple[pathlib.Path, dict[str, Any]]] = []
    for labels in sorted(fixtures.glob("*.labels.json")):
        doc = next(
            (
                p
                for p in fixtures.glob(labels.name.replace(".labels.json", ".*"))
                if not p.name.endswith(".labels.json") and p.suffix.casefold() in _INGEST_BY_SUFFIX
            ),
            None,
        )
        if doc is not None:
            corpus.append((doc, json.loads(labels.read_text(encoding="utf-8"))))
    return corpus


def score(expected: set[tuple[str, ...]], found: set[tuple[str, ...]]) -> dict[str, float]:
    tp = len(expected & found)
    fp = len(found - expected)
    fn = len(expected - found)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def _profile_judge_metrics(
    corpus: list[tuple[pathlib.Path, dict[str, Any]]],
    *,
    provider: LLMProvider | None = None,
    detect_agent_factory: Callable[[], DetectAgent] | None = None,
) -> dict[str, float]:
    """Посчитать профиль и судью напрямую, пока общий pipeline ещё не собран.

    ``provider`` и ``detect_agent_factory`` — параметры матричного
    бенчмарка (``masker.bench_matrix``, К4): по умолчанию оба сохраняют
    прежнее поведение (``get_provider()`` из конфигурации и голый
    ``DetectAgent()``), поэтому обычный ``make eval`` этой правки не
    замечает.
    """
    matched = 0
    party_matched = 0
    covered = 0
    pure = 0
    role_checked = 0
    role_correct = 0
    critical_questions = 0
    questions = 0
    policy_questions = 0
    critical_unmasked = 0
    synonyms_path = FIXTURES.parent / "role_synonyms.json"
    synonyms = (
        json.loads(synonyms_path.read_text(encoding="utf-8")) if synonyms_path.exists() else {}
    )
    for path, labels in corpus:
        document = _ingest(path)
        #: Роль «есть в документе» только когда её назвала предусмотренная
        #: проектом явная конструкция. Одно слово в ячейке XLSX или рядом с
        #: реквизитом не даёт права выдумывать роль (см. `find_labels`).
        documented_roles = {
            normalize_label(label)
            for segment in document.segments
            for _offset, label in find_labels(segment.text)
        }
        agent = detect_agent_factory() if detect_agent_factory is not None else DetectAgent()
        detection = agent.detect(document)
        active_provider = provider if provider is not None else get_provider()
        profiles = ProfileAgent(active_provider).profile(document, detection)
        judge = JudgeAgent().judge(detection, profiles)
        profile_by_value = {
            (member.entity.type, _collapse(member.entity.text)): profile
            for profile in profiles.profiles
            for member in profile.members
        }
        for item in labels["entities"]:
            profile = profile_by_value.get((item["type"], _collapse(item["text"])))
            if profile is None:
                continue
            matched += 1
            if profile.role_title:
                covered += 1
            party = item.get("party")
            if party:
                party_matched += 1
                peers = [
                    member
                    for member in profile.members
                    if any(
                        candidate["type"] == member.entity.type
                        and _collapse(candidate["text"]) == _collapse(member.entity.text)
                        and candidate.get("party") == party
                        for candidate in labels["entities"]
                    )
                ]
                pure += int(bool(peers))
                expected_roles = {normalize_label(value) for value in synonyms.get(party, [])}
                # У профиля с найденной явной меткой роль уже есть в документе,
                # даже когда она расходится с эталоном (это как раз ошибка,
                # которую должна считать метрика). Пустой профиль допустим в
                # знаменатель лишь когда ожидаемая роль явно названа в тексте.
                if expected_roles and (profile.role_title or expected_roles & documented_roles):
                    role_checked += 1
                    role_correct += int(profile.role_title.casefold() in expected_roles)
        questions += len(judge.questions)
        refs_to_entities = {
            member.ref: member.entity for profile in profiles.profiles for member in profile.members
        }
        critical_questions += sum(
            1
            for question in judge.questions
            for ref in question.refs
            if ref in refs_to_entities and is_critical(refs_to_entities[ref].type)
        )
        policy_questions += len(PolicyAgent().questions(detection, profiles))
        # Неинтерактивный прогон: никто не спрашивал — только уверенность
        # судьи и защита критичных типов могут повлиять на решение (раздел 6
        # плана T1.5.1, needs_human/finalize_node). Порог critical_unmasked
        # == 0 держит инвариант «двойное подтверждение обязательно».
        policy_result = PolicyAgent().apply(
            detection,
            profiles,
            judge.verdicts,
            [],
            [],
            {},
            allow_unmask_critical=False,
        )
        critical_unmasked += len(policy_result.critical_unmasked)
    return {
        "cluster_purity": pure / party_matched if party_matched else 1.0,
        "role_coverage": covered / matched if matched else 1.0,
        "role_accuracy": role_correct / role_checked if role_checked else 1.0,
        "critical_in_questions": float(critical_questions),
        "questions_per_document": questions / len(corpus) if corpus else 0.0,
        "policy_questions_per_document": policy_questions / len(corpus) if corpus else 0.0,
        "critical_unmasked": float(critical_unmasked),
    }


def _print_profile_judge(metrics: dict[str, float]) -> list[str]:
    print("\nПРОФИЛИ И СУДЬЯ")
    for name, value in metrics.items():
        print(f"{name:<30}{value:.3f}")
    failures: list[str] = []
    if metrics["cluster_purity"] < MIN_CLUSTER_PURITY:
        failures.append("cluster_purity ниже порога")
    if metrics["role_coverage"] < MIN_ROLE_COVERAGE:
        failures.append("role_coverage ниже порога")
    if metrics["role_accuracy"] < MIN_ROLE_ACCURACY:
        failures.append(f"role_accuracy {metrics['role_accuracy']:.3f} < {MIN_ROLE_ACCURACY}")
    if metrics["questions_per_document"] > MAX_QUESTIONS:
        failures.append("слишком много вопросов судьи")
    if metrics["critical_in_questions"] != 0:
        failures.append("критичные сущности попали в вопросы")
    if metrics["policy_questions_per_document"] > MAX_POLICY_QUESTIONS:
        failures.append("слишком много вопросов политики (типы/профили)")
    if metrics["critical_unmasked"] > MAX_CRITICAL_UNMASKED:
        failures.append("критичный тип снят без двойного подтверждения (critical_unmasked)")
    return failures


@dataclass
class MaskingMetrics:
    """Результат прогона ``mask_and_validate`` по одному корпусу.

    Общий контейнер для основного корпуса, holdout и негативного (К2) —
    раньше эти числа жили локальными переменными внутри ``run()`` и не
    подлежали переиспользованию.
    """

    by_type: dict[str, dict[str, set[tuple[str, ...]]]] = field(
        default_factory=lambda: defaultdict(lambda: {"expected": set(), "found": set()})
    )
    by_format: dict[str, dict[str, set[tuple[str, ...]]]] = field(
        default_factory=lambda: defaultdict(lambda: {"expected": set(), "found": set()})
    )
    leaked_total: int = 0
    duplicate_markers: int = 0
    inconsistent_markers: int = 0
    layout_removed_chars: int = 0
    layout_failures: list[str] = field(default_factory=list)
    render_failures: list[str] = field(default_factory=list)
    #: Сколько документов провалили сертификат обезличивания (план М3) — по
    #: любому из трёх пунктов. Счётчик документов, а не пунктов: один
    #: провалившийся документ не должен размножаться на три строки в сумме.
    certificate_failures: int = 0
    certificate_failure_details: list[str] = field(default_factory=list)
    #: Сколько раз область подсветки маркера накрыла живой символ в
    #: ВЫХОДНОМ PDF (план М5) — см. ``highlight_overlap_count``.
    highlight_overlaps: int = 0


def _mask_corpus(
    corpus: list[tuple[pathlib.Path, dict[str, Any]]],
    *,
    rules_only: bool = False,
    llm: LLMProvider | None = None,
) -> MaskingMetrics:
    """Прогнать ``mask_and_validate`` по каждому документу корпуса и собрать метрики.

    Общая часть основного, holdout- и негативного прогонов (К2, план
    `docs/plans/product-completion.md`): раньше это тело жило только внутри
    `run()` и не могло быть вызвано второй раз для `fixtures/holdout` и
    `fixtures/negative` без копипаста.

    ``rules_only`` и ``llm`` — параметры матричного бенчмарка
    (``masker.bench_matrix``, К4): по умолчанию оба сохраняют прежнее
    поведение (обычный набор детекторов, граф без LLM), поэтому
    обычный ``make eval`` этой правки не замечает.
    """
    from masker.pipeline import mask_and_validate

    metrics = MaskingMetrics()
    for path, labels in corpus:
        fmt = path.suffix.casefold().lstrip(".")
        custom_types = labels.get("custom_types", [])
        try:
            with mask_and_validate(
                path,
                types=list(EntityType),
                custom_types=custom_types,
                rules_only=rules_only,
                llm=llm,
            ) as result:
                for item in labels["entities"]:
                    key = (path.name, item["type"], _collapse(item["text"]))
                    metrics.by_type[item["type"]]["expected"].add(key)
                    metrics.by_format[fmt]["expected"].add(key)
                for repl in result.plan.replacements:
                    key = (path.name, repl.entity.type, _collapse(repl.entity.text))
                    metrics.by_type[repl.entity.type]["found"].add(key)
                    metrics.by_format[fmt]["found"].add(key)
                metrics.leaked_total += len(result.validation.leaked)
                metrics.duplicate_markers += duplicate_marker_count(result.plan, result.artifacts)
                metrics.inconsistent_markers += inconsistent_marker_count(
                    result.plan, result.render_degradations
                )
                for layout in result.validation.layout:
                    metrics.layout_removed_chars += layout.removed_chars
                    if layout.removed_chars:
                        metrics.layout_failures.append(
                            f"{path.name}/{layout.artifact}: removed={layout.removed_chars} "
                            f"pages={list(layout.pages)} {layout.first_diff}"
                        )
                certificate = result.validation.certificate
                if certificate is not None and not certificate.ok:
                    metrics.certificate_failures += 1
                    failed_checks = "; ".join(
                        f"{check.name}: {check.detail}"
                        for check in certificate.checks
                        if not check.ok
                    )
                    metrics.certificate_failure_details.append(f"{path.name}: {failed_checks}")
                metrics.highlight_overlaps += highlight_overlap_count(
                    result.plan, path, result.artifacts
                )
        except RunFailedError as error:
            # Не глотать тихо: документ выпадает из P/R/F1 (план на него не
            # посчитан), но факт и место падения обязаны остаться видимыми —
            # иначе один аномальный документ маскировал бы метрики по всем
            # остальным, ровно то, чего требовалось избежать (Д7 наоборот).
            metrics.render_failures.append(f"{path.name}: {error}")
    return metrics


def _print_main_corpus(metrics: MaskingMetrics, registry: EntityTypeRegistry) -> list[str]:
    print(f"{'тип':<18}{'P':>7}{'R':>7}{'F1':>7}{'FN':>5}{'FP':>5}")
    failures: list[str] = []
    for name in sorted(metrics.by_type):
        m = score(metrics.by_type[name]["expected"], metrics.by_type[name]["found"])
        print(
            f"{name:<18}{m['precision']:>7.3f}{m['recall']:>7.3f}"
            f"{m['f1']:>7.3f}{m['fn']:>5}{m['fp']:>5}"
        )
        critical = registry.is_critical(name)
        min_recall = (
            MIN_RECALL_CRITICAL if critical else _MIN_RECALL_OVERRIDE.get(name, MIN_RECALL_OTHER)
        )
        min_prec = _MIN_PRECISION_OVERRIDE.get(name, MIN_PRECISION)
        if m["recall"] < min_recall:
            failures.append(f"{name}: recall {m['recall']:.3f} < {min_recall}")
        if m["precision"] < min_prec:
            failures.append(f"{name}: precision {m['precision']:.3f} < {min_prec}")

    print(f"\nФОРМАТЫ\n{'формат':<18}{'P':>7}{'R':>7}{'F1':>7}{'FN':>5}{'FP':>5}")
    for fmt in sorted(metrics.by_format):
        m = score(metrics.by_format[fmt]["expected"], metrics.by_format[fmt]["found"])
        print(
            f"{fmt:<18}{m['precision']:>7.3f}{m['recall']:>7.3f}"
            f"{m['f1']:>7.3f}{m['fn']:>5}{m['fp']:>5}"
        )

    print(f"\nleaked_total{metrics.leaked_total:>22}")
    print(f"duplicate_markers{metrics.duplicate_markers:>17}")
    print(f"inconsistent_markers{metrics.inconsistent_markers:>14}")
    print(f"layout_removed_chars{metrics.layout_removed_chars:>14}")
    for failure in metrics.layout_failures:
        print(f"  {failure}")
    print(f"certificate_failures{metrics.certificate_failures:>14}")
    for failure in metrics.certificate_failure_details:
        print(f"  {failure}")
    print(f"highlight_overlaps{metrics.highlight_overlaps:>16}")
    print(f"render_failures{len(metrics.render_failures):>19}")
    for failure in metrics.render_failures:
        print(f"  {failure}")
    if metrics.leaked_total > MAX_LEAKED_TOTAL:
        failures.append(
            f"leaked_total {metrics.leaked_total} > {MAX_LEAKED_TOTAL} — утечка в артефактах"
        )
    if metrics.duplicate_markers > MAX_DUPLICATE_MARKERS:
        failures.append(
            f"duplicate_markers {metrics.duplicate_markers} > {MAX_DUPLICATE_MARKERS} — "
            "маркер вставлен не один раз на Replacement"
        )
    if metrics.inconsistent_markers > MAX_INCONSISTENT_MARKERS:
        failures.append(
            f"inconsistent_markers {metrics.inconsistent_markers} > "
            f"{MAX_INCONSISTENT_MARKERS} — одна группа отрендерена больше чем одной строкой"
        )
    if metrics.layout_removed_chars > MAX_LAYOUT_REMOVED_CHARS:
        failures.append(
            f"layout_removed_chars {metrics.layout_removed_chars} > {MAX_LAYOUT_REMOVED_CHARS} — "
            "прямоугольник редакции стёр текст вне своих замен (Д10): "
            + "; ".join(metrics.layout_failures)
        )
    if len(metrics.render_failures) > MAX_RENDER_FAILURES:
        failures.append(
            f"render_failures {len(metrics.render_failures)} > {MAX_RENDER_FAILURES} — "
            "рендер упал на документе(ах) корпуса: " + "; ".join(metrics.render_failures)
        )
    if metrics.certificate_failures > MAX_CERTIFICATE_FAILURES:
        failures.append(
            f"certificate_failures {metrics.certificate_failures} > "
            f"{MAX_CERTIFICATE_FAILURES} — сертификат обезличивания (план М3) не прошёл "
            "хотя бы один пункт: " + "; ".join(metrics.certificate_failure_details)
        )
    if metrics.highlight_overlaps > MAX_HIGHLIGHT_OVERLAPS:
        failures.append(
            f"highlight_overlaps {metrics.highlight_overlaps} > {MAX_HIGHLIGHT_OVERLAPS} — "
            "область подсветки маркера накрыла живой символ в выходном PDF (план М5)"
        )
    return failures


def _aggregate(
    by_type: dict[str, dict[str, set[tuple[str, ...]]]], registry: EntityTypeRegistry
) -> tuple[dict[str, int], dict[str, int]]:
    """Сложить TP/FP/FN по всем типам раздельно для критичных и остальных.

    Holdout-корпус (К2) слишком мал (2–4 примера на тип), чтобы держать
    порог по каждому типу отдельно — единичный промах на одном документе
    валил бы ворота как системная деградация. Критичные типы, наоборот,
    обязаны остаться на recall = 1.0 даже поодиночке, поэтому считаются
    отдельной суммой.
    """
    critical = {"tp": 0, "fp": 0, "fn": 0}
    other = {"tp": 0, "fp": 0, "fn": 0}
    for name, sets in by_type.items():
        m = score(sets["expected"], sets["found"])
        bucket = critical if registry.is_critical(name) else other
        bucket["tp"] += int(m["tp"])
        bucket["fp"] += int(m["fp"])
        bucket["fn"] += int(m["fn"])
    return critical, other


def _print_holdout(metrics: MaskingMetrics, registry: EntityTypeRegistry) -> list[str]:
    """К2: секция HOLDOUT — те же P/R/F1 по типам, но на документах,
    которые никто не смотрит при настройке детекторов. Печатается и
    проверяется отдельно от основного корпуса — разница между corpus recall
    и holdout recall и есть честная оценка переобучения.
    """
    print("\nHOLDOUT (fixtures/holdout — детекторы на этих документах не настраивались)")
    print(f"{'тип':<18}{'P':>7}{'R':>7}{'F1':>7}{'FN':>5}{'FP':>5}")
    for name in sorted(metrics.by_type):
        expected = metrics.by_type[name]["expected"]
        found = metrics.by_type[name]["found"]
        m = score(expected, found)
        print(
            f"{name:<18}{m['precision']:>7.3f}{m['recall']:>7.3f}"
            f"{m['f1']:>7.3f}{m['fn']:>5}{m['fp']:>5}"
        )
        for missing in sorted(expected - found):
            print(f"    НЕ НАЙДЕНО: {missing[0]}: {missing[2]!r}")

    critical, other = _aggregate(metrics.by_type, registry)
    critical_recall = (
        critical["tp"] / (critical["tp"] + critical["fn"])
        if critical["tp"] + critical["fn"]
        else 1.0
    )
    other_recall = other["tp"] / (other["tp"] + other["fn"]) if other["tp"] + other["fn"] else 1.0
    other_precision = (
        other["tp"] / (other["tp"] + other["fp"]) if other["tp"] + other["fp"] else 1.0
    )
    print(
        f"holdout_recall_critical{critical_recall:>10.3f}  "
        f"({critical['tp']}/{critical['tp'] + critical['fn']})"
    )
    print(f"holdout_recall_other{other_recall:>13.3f}  ({other['tp']}/{other['tp'] + other['fn']})")
    print(
        f"holdout_precision_other{other_precision:>10.3f}  "
        f"({other['tp']}/{other['tp'] + other['fp']})"
    )
    print(f"holdout_leaked_total{metrics.leaked_total:>13}")
    print(f"holdout_duplicate_markers{metrics.duplicate_markers:>8}")
    print(f"holdout_inconsistent_markers{metrics.inconsistent_markers:>4}")
    print(f"holdout_certificate_failures{metrics.certificate_failures:>4}")
    for failure in metrics.certificate_failure_details:
        print(f"  {failure}")
    print(f"holdout_highlight_overlaps{metrics.highlight_overlaps:>6}")
    for failure in metrics.render_failures:
        print(f"  {failure}")

    failures: list[str] = []
    if critical_recall < MIN_RECALL_CRITICAL:
        failures.append(
            f"holdout: критичный тип не найден, recall {critical_recall:.3f} < "
            f"{MIN_RECALL_CRITICAL}"
        )
    if other_recall < MIN_HOLDOUT_RECALL_OTHER:
        failures.append(f"holdout_recall_other {other_recall:.3f} < {MIN_HOLDOUT_RECALL_OTHER}")
    if other_precision < MIN_HOLDOUT_PRECISION_OTHER:
        failures.append(
            f"holdout_precision_other {other_precision:.3f} < {MIN_HOLDOUT_PRECISION_OTHER}"
        )
    if metrics.leaked_total > MAX_LEAKED_TOTAL:
        failures.append(f"holdout leaked_total {metrics.leaked_total} > {MAX_LEAKED_TOTAL}")
    if metrics.duplicate_markers > MAX_DUPLICATE_MARKERS:
        failures.append(
            f"holdout duplicate_markers {metrics.duplicate_markers} > {MAX_DUPLICATE_MARKERS}"
        )
    if metrics.inconsistent_markers > MAX_INCONSISTENT_MARKERS:
        failures.append(
            f"holdout inconsistent_markers {metrics.inconsistent_markers} > "
            f"{MAX_INCONSISTENT_MARKERS}"
        )
    if metrics.certificate_failures > MAX_CERTIFICATE_FAILURES:
        failures.append(
            f"holdout certificate_failures {metrics.certificate_failures} > "
            f"{MAX_CERTIFICATE_FAILURES}: {'; '.join(metrics.certificate_failure_details)}"
        )
    if metrics.highlight_overlaps > MAX_HIGHLIGHT_OVERLAPS:
        failures.append(
            f"holdout highlight_overlaps {metrics.highlight_overlaps} > {MAX_HIGHLIGHT_OVERLAPS}"
        )
    if metrics.render_failures:
        failures.append(f"holdout render_failures: {'; '.join(metrics.render_failures)}")
    return failures


def _print_negative(metrics: MaskingMetrics) -> list[str]:
    """К2: секция ЛОЖНЫЕ — negative-корпус без единой PII. Recall тут не
    имеет смысла (нечего находить), считаются только ложные срабатывания.
    """
    print("\nЛОЖНЫЕ (fixtures/negative — документ без единой PII, каждое срабатывание — ошибка)")
    print(f"{'тип':<18}{'FP':>7}")
    total_fp = 0
    for name in sorted(metrics.by_type):
        found = metrics.by_type[name]["found"]
        if not found:
            continue
        total_fp += len(found)
        print(f"{name:<18}{len(found):>7}")
        for item in sorted(found):
            print(f"    {item[0]}: {item[2]!r}")
    print(f"{'ИТОГО':<18}{total_fp:>7}")
    print(f"negative_certificate_failures{metrics.certificate_failures:>4}")
    for failure in metrics.certificate_failure_details:
        print(f"  {failure}")
    print(f"negative_highlight_overlaps{metrics.highlight_overlaps:>6}")

    failures: list[str] = []
    if total_fp > MAX_NEGATIVE_FALSE_POSITIVES:
        failures.append(
            f"негативный корпус: {total_fp} ложных срабатываний > {MAX_NEGATIVE_FALSE_POSITIVES}"
        )
    if metrics.leaked_total > MAX_LEAKED_TOTAL:
        failures.append(f"негативный корпус leaked_total {metrics.leaked_total} > 0")
    if metrics.certificate_failures > MAX_CERTIFICATE_FAILURES:
        failures.append(
            f"негативный корпус certificate_failures {metrics.certificate_failures} > "
            f"{MAX_CERTIFICATE_FAILURES}: {'; '.join(metrics.certificate_failure_details)}"
        )
    if metrics.highlight_overlaps > MAX_HIGHLIGHT_OVERLAPS:
        failures.append(
            f"негативный корпус highlight_overlaps {metrics.highlight_overlaps} > "
            f"{MAX_HIGHLIGHT_OVERLAPS}"
        )
    if metrics.render_failures:
        failures.append(f"негативный корпус render_failures: {'; '.join(metrics.render_failures)}")
    return failures


def run(
    gate: bool,
    *,
    corpus: list[tuple[pathlib.Path, dict[str, Any]]] | None = None,
    include_supplementary: bool = True,
) -> int:
    """Посчитать метрики по полному либо явно переданному основному корпусу.

    Обычный CLI-путь не передаёт аргументы и поэтому, как и прежде, измеряет
    весь ``fixtures/labeled`` вместе с holdout и negative-корпусами. Явный
    ``corpus`` нужен для узких тестов самих ворот: им достаточно доказать,
    что конкретный инвариант способен провалить gate, а не заново измерять
    все документы. У такого узкого запуска сопутствующие корпуса отключают
    через ``include_supplementary=False``.

    Синтетические сканы (``scan_synth_*``) в основной корпус не попадают:
    это входные данные OCR-ветки, у них своя проверка, и в общих
    precision/recall они мерили бы качество распознавания, а не детекции.
    """
    if corpus is None:
        corpus = [
            (path, labels)
            for path, labels in load_corpus()
            if not path.stem.startswith("scan_synth_")
        ]
    profile_failures = _print_profile_judge(_profile_judge_metrics(corpus)) if corpus else []
    # Метаморфный корпус (К1) не зависит от собранного pipeline — только от
    # слоя детекции, поэтому меряется и здесь до проверки на masker.pipeline.
    metamorphic_failures = _print_metamorphic(evalgen.evaluate())
    try:
        from masker.pipeline import mask_and_validate  # noqa: F401 — проверка наличия модуля
    except ImportError:
        print("МЕТРИКИ ПРОПУЩЕНЫ: masker.pipeline ещё не реализован.")
        print("После T1.10 этот пропуск обязан исчезнуть — иначе ворота декоративны.")
        return 1 if gate and (profile_failures or metamorphic_failures) else 0

    if not corpus:
        print("МЕТРИКИ ПРОПУЩЕНЫ: в fixtures/labeled нет размеченных документов.")
        return 1

    registry = corpus_registry(corpus)
    failures = _print_main_corpus(_mask_corpus(corpus), registry)
    failures.extend(profile_failures)
    failures.extend(metamorphic_failures)

    if include_supplementary:
        # К2 — holdout: те же метрики отдельной секцией на документах, на
        # которых никто не настраивает детекторы.
        holdout_corpus = load_corpus(FIXTURES_HOLDOUT)
        if holdout_corpus:
            holdout_registry = corpus_registry(holdout_corpus)
            failures.extend(_print_holdout(_mask_corpus(holdout_corpus), holdout_registry))
        else:
            print("\nHOLDOUT ПРОПУЩЕН: fixtures/holdout пуст.")

        # К2 — негативный корпус: документ без единой PII, считаются только FP.
        negative_corpus = load_corpus(FIXTURES_NEGATIVE)
        if negative_corpus:
            failures.extend(_print_negative(_mask_corpus(negative_corpus)))
        else:
            print("\nЛОЖНЫЕ ПРОПУЩЕНЫ: fixtures/negative пуст.")

    # Скан-корпус: scan_synth_* — синтетические сканы, FakeOCR из .fake_ocr.json.
    scan_corpus = [
        (path, labels) for path, labels in load_corpus() if path.stem.startswith("scan_synth_")
    ]
    if scan_corpus:
        scan_registry = corpus_registry(scan_corpus)
        failures.extend(_print_scan_corpus(_mask_scan_corpus(scan_corpus), scan_registry))
    else:
        print("\nСКАН ПРОПУЩЕН: в fixtures/labeled нет scan_synth_* файлов.")

    if failures and gate:
        print("\nПОРОГИ НЕ ВЗЯТЫ:")
        for f in failures:
            print(f"  {f}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Метрики обезличивания по корпусу")
    parser.add_argument("--gate", action="store_true", help="ненулевой код при провале порогов")
    args = parser.parse_args()
    return run(gate=args.gate)


if __name__ == "__main__":
    sys.exit(main())

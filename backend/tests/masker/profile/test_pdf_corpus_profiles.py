"""Регрессия сборки профилей сторон на реальных PDF (план «Профили сторон
на PDF», 13.09.2026).

До этой правки структурный профиль на PDF был либо выключен целиком
(веб-API — `api/services/run_service.py`, см. `test_profile_enabled_matches_cli`
в `tests/api`), либо собирался неверно: `_anchor_kind` не меняется на PDF
(каждый сегмент — `("page", …)`), поэтому метка роли, подхваченная из
формулировки, текла до конца документа и склеивала обе стороны в один
профиль. Замер по `fixtures/real-contracts/open-contracts` (см.
`scripts/check_profiles.py`) до правки:

    ipklh-2022-01-11.pdf        247 сущностей → 10 профилей, крупнейший 139
    edukirovsk-2018-659372.pdf  315 сущностей → 201 профиль (190 из них — по 1 члену)

Эти два документа и держат регрессию ниже.
"""

from __future__ import annotations

import pathlib

from masker.detect.agent import DetectAgent
from masker.eval import _ingest
from masker.model import EntityType
from masker.profile import ProfileAgent

_CORPUS = pathlib.Path(__file__).parents[3] / "fixtures" / "real-contracts" / "open-contracts"


def _profile(path: pathlib.Path):
    document = _ingest(path)
    detection = DetectAgent().detect(document)
    return document, detection, ProfileAgent().profile(document, detection)


def test_ipklh_splits_both_parties_by_inn() -> None:
    """Заказчик (ИНН 2446000650) и Поставщик (ИНН 2466100100) — разные
    профили. До правки оба ИНН оказывались в одном профиле «Заказчик» на
    139 участников (`_anchor_kind` постоянен на PDF — метка не сбрасывалась
    между сегментами страницы, см. `blocks.py::_scope_broken`)."""
    _, _, result = _profile(_CORPUS / "ipklh-2022-01-11.pdf")
    profiles_by_inn: dict[str, set[str]] = {}
    for profile in result.profiles:
        for member in profile.members:
            if member.entity.type is EntityType.INN:
                profiles_by_inn.setdefault(profile.id, set()).add(member.entity.text)
    customer_profile = next(pid for pid, inns in profiles_by_inn.items() if "2446000650" in inns)
    supplier_profile = next(pid for pid, inns in profiles_by_inn.items() if "2466100100" in inns)
    assert customer_profile != supplier_profile


def test_edukirovsk_does_not_collapse_into_singleton_dust() -> None:
    """До правки `_is_heading` считал заголовком почти любую короткую строку
    (73% сегментов PDF без сущностей ей не были) и резал документ на 374
    блока, из которых 190 становились профилями-одиночками (телефон,
    e-mail сами по себе — не сторона, см. `cluster.py::_PARTY_FORMING_TYPES`).
    Порог — с запасом от текущего результата (после правки), а не от
    теоретического минимума: он ловит регресс, а не требует идеала."""
    _, detection, result = _profile(_CORPUS / "edukirovsk-2018-659372.pdf")
    singles = sum(1 for profile in result.profiles if len(profile.members) == 1)
    assert len(result.profiles) <= 80, len(result.profiles)
    assert singles <= 30, singles
    assert len(detection.entities) > 200  # сам корпус не обеднел


def test_multi_inn_profiles_do_not_grow_beyond_known_debt() -> None:
    """Не инвариант «ноль», а потолок против регресса.

    После правки у части корпуса профиль с непустой ролью всё ещё содержит
    два разных ИНН — но это не склейка двух сторон, а третье лицо без
    собственной роли внутри верно определённого блока (банк или
    казначейство в тех же реквизитах: «ЗАКАЗЧИК» … ИНН <сторона> … Р/счёт в
    ПАО «Сбербанк» ИНН <банк>). Отличить это от настоящей склейки сторон
    затратно (нужна геометрия колонок — см. открытый вопрос в плане), а
    выдавать это за пройденный тест — заведомая ложь. Порог фиксирует
    состояние ПОСЛЕ правки (было гораздо хуже — см. `test_ipklh_...` выше,
    где до правки все ИНН документа сходились в один профиль на 139
    участников) и растёт только вместе с сознательным изменением, а не
    молча."""
    KNOWN_DEBT = 10
    violations: list[tuple[str, str, set[str]]] = []
    for path in sorted(_CORPUS.glob("*.pdf")):
        document = _ingest(path)
        if not document.segments:
            continue  # скан без текстового слоя — вне охвата этого теста
        detection = DetectAgent().detect(document)
        result = ProfileAgent().profile(document, detection)
        for profile in result.profiles:
            if not profile.role_title:
                continue
            inns = {
                member.entity.text
                for member in profile.members
                if member.entity.type is EntityType.INN
            }
            if len(inns) > 1:
                violations.append((path.name, profile.marker_label, inns))
    assert len(violations) <= KNOWN_DEBT, violations

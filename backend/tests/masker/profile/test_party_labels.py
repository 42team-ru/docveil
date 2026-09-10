"""И2-1: роль стороны ≠ должность и ≠ мусор из таблицы.

`SIGNATURE` — голая регулярка «Слово:» в начале строки, и до этого шага
принимала любую такую метку за роль стороны, включая должность подписанта
(«Директор:») и текст ячейки таблицы («Объединённая ячейка:»). Метка от
`SIGNATURE` теперь допускается только если она входит в список ролей-сторон
(`profile/data/party_roles.yaml`) или уже введена этим же текстом через
`PREAMBLE`. `PREAMBLE` и `REQUISITES` не меняются — они не проверяются.
"""

from __future__ import annotations

from pathlib import Path

from masker.detect.agent import DetectAgent
from masker.ingest.docx_ingest import ingest_docx
from masker.ingest.pdf_ingest import ingest_pdf
from masker.profile import ProfileAgent
from masker.profile.labels import find_labels

FIXTURES = Path(__file__).parents[3] / "fixtures" / "labeled"


def test_signature_position_is_not_a_party_role() -> None:
    """«Директор:» — должность подписанта, а не роль стороны договора."""
    assert find_labels("Директор: Иванов Иван Иванович") == []


def test_signature_table_cell_junk_is_not_a_party_role() -> None:
    """Текст ячейки таблицы не должен становиться ролью стороны."""
    assert find_labels("Объединённая ячейка: ИНН 3662103003") == []


def test_signature_generic_word_is_not_a_party_role() -> None:
    """«Организация:» — не должность, но и не название конкретной роли стороны."""
    assert find_labels("Организация: ООО «Ромашка»") == []


def test_signature_known_party_role_is_still_accepted() -> None:
    """Список ролей-сторон не должен по пути отсечь настоящую роль."""
    assert find_labels("Поставщик: ООО «ТехноСнаб»") == [(0, "поставщик")]
    assert find_labels("Исполнитель: ООО «ШБС»") == [(0, "исполнитель")]


def test_signature_accepts_role_already_introduced_by_preamble() -> None:
    """Метка, которой нет в статичном списке, но которую документ сам ввёл
    через преамбулу («именуемое в дальнейшем «X»»), не выдумана — её можно
    использовать и там, где она повторяется через `SIGNATURE`.

    `SIGNATURE` (`^...`) матчится только с начала переданного текста —
    поэтому в тесте сигнатурная строка идёт первой, а преамбула — следом
    в том же тексте (план T2.2.1: на сегменте-блоке несколько предложений
    склеены в одну строку, оба контекста реально оказываются в одном вызове
    `find_labels`)."""
    text = (
        "Учреждение: МАОУ гимназия №144. "
        '____, именуемое в дальнейшем "Учреждение", с одной стороны.'
    )
    labels = find_labels(text)
    assert (text.index("Учреждение:"), "учреждение") in labels


def test_signature_unknown_label_without_preamble_is_still_rejected() -> None:
    """Без списка ролей и без преамбулы `SIGNATURE` не имеет права выдумывать роль."""
    assert find_labels("Учреждение: МАОУ гимназия №144") == []


def test_contract_pdf_01_no_profile_gets_director_as_role() -> None:
    """Приёмка И2-1, п.1: на contract_pdf_01.pdf ни один профиль не получает
    role_title 'Директор' — это должность подписанта, а не роль стороны."""
    document = ingest_pdf(FIXTURES / "contract_pdf_01.pdf")
    detection = DetectAgent().detect(document)
    profiles = ProfileAgent().profile(document, detection).profiles
    role_titles = {profile.role_title for profile in profiles}
    assert "Директор" not in role_titles


def test_contract_05_tables_no_profile_gets_merged_cell_as_role() -> None:
    """Приёмка И2-1, п.1: на contract_05_tables.docx ни один профиль не получает
    role_title 'Объединённая ячейка' — это содержимое ячейки, а не роль стороны."""
    document = ingest_docx(FIXTURES / "contract_05_tables.docx")
    detection = DetectAgent().detect(document)
    profiles = ProfileAgent().profile(document, detection).profiles
    role_titles = {profile.role_title for profile in profiles}
    assert "Объединённая ячейка" not in role_titles


def test_contract_05_tables_profile_without_role_gets_side_marker() -> None:
    """Приёмка И2-1, п.2: профиль, оставшийся без роли (текст документа не
    называет её вовсе), получает СТОРОНА-N, а не выдуманную роль."""
    document = ingest_docx(FIXTURES / "contract_05_tables.docx")
    detection = DetectAgent().detect(document)
    profiles = ProfileAgent().profile(document, detection).profiles
    horizont_profile = next(
        profile
        for profile in profiles
        for member in profile.members
        if "Горизонт" in member.entity.text
    )
    assert horizont_profile.role_title == ""
    assert horizont_profile.marker_label.startswith("СТОРОНА-")

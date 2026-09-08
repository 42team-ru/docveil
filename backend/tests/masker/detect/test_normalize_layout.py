"""Тесты слоя нормализации вёрстки перед детекцией (план Р1)."""

from __future__ import annotations

from masker.detect import DetectAgent, default_detectors
from masker.detect.normalize_layout import normalize_for_detection
from masker.model import Anchor, Document, EntityType, Segment

NBSP = " "
THIN_SPACE = " "
HAIR_SPACE = " "
ZERO_WIDTH_SPACE = "​"
SOFT_HYPHEN = "­"

#: ИНН, валидный по контрольной сумме (используется во всех пяти
#: приёмочных кейсах Р1 — без валидной контрольной суммы `RuleDetector` не
#: примет кандидата вне зависимости от того, что сделает нормализация).
VALID_INN = "3662103003"


def _document(text: str) -> Document:
    return Document(
        path="test.docx",
        fmt="docx",
        segments=[Segment(text=text, anchor=Anchor(fmt="docx", locator=("body", 0)), order=0)],
    )


def _detect_inn(text: str) -> list[str]:
    result = DetectAgent(default_detectors()).detect(_document(text))
    return [entity.text for entity in result.entities if entity.type == EntityType.INN]


def _map_roundtrip(text: str, mapping: list[int], start: int, end: int) -> str:
    """Применить карту смещений к спану ``[start, end)``, найденному в
    нормализованном тексте, и вернуть срез исходного ``text``. Именно так
    `DetectAgent._remap_entities` восстанавливает координаты — тест
    дублирует только саму формулу, не код агента."""
    return text[mapping[start] : mapping[end]]


class TestNormalizeForDetection:
    """Юнит-тесты самой функции: текст + карта, без детекторов."""

    def test_returns_identity_map_for_plain_text(self) -> None:
        text = "обычный текст без вёрстки"
        normalized, mapping = normalize_for_detection(text)
        assert normalized == text
        assert mapping == [*range(len(text)), len(text)]

    def test_collapses_two_or_more_spaces_to_one(self) -> None:
        text = "Татьяны  Ивановны"
        normalized, mapping = normalize_for_detection(text)
        assert normalized == "Татьяны Ивановны"
        # Оба слова целиком восстанавливаются из нормализованного текста —
        # карта не теряет ни одного символа исходного текста.
        assert _map_roundtrip(text, mapping, 0, len(normalized)) == text

    def test_end_offset_uses_the_map_not_the_length_difference(self) -> None:
        """Спан после схлопнутого прогона не «уезжает».

        Наивная реализация, которая считает конец спана как
        ``mapping[start] + (end - start)`` (предполагая, что нормализация
        не меняет длину строки), для спана, целиком включающего схлопнутый
        двойной пробел, промахивается на число лишних пробелов: в исходном
        тексте между словами два пробела, в нормализованном — один.
        """
        text = "Пётр  Иванов"
        normalized, mapping = normalize_for_detection(text)
        assert normalized == "Пётр Иванов"
        start, end = 0, len(normalized)
        naive_end = mapping[start] + (end - start)
        real_end = mapping[end]
        assert real_end != naive_end, "тест не показателен: длины совпали случайно"
        assert text[mapping[start] : real_end] == text
        assert text[mapping[start] : naive_end] != text

    def test_nbsp_thin_hair_and_zero_width_space_between_letters_become_regular_space(self) -> None:
        """Между буквами «мягкий» пробел не склеивается — иначе типографская
        защита предлога от отрыва в конце строки («в NBSP доме») испортила
        бы обычный текст договора."""
        for exotic in (NBSP, THIN_SPACE, HAIR_SPACE, ZERO_WIDTH_SPACE):
            normalized, _ = normalize_for_detection(f"два{exotic}слова")
            assert normalized == "два слова"

    def test_nbsp_between_two_digits_is_glued(self) -> None:
        """Между цифрами «мягкий» пробел — группировка одного значения
        (реквизита), а не граница двух чисел: единственный случай, где эти
        символы схлопываются без остатка, а не в обычный пробел."""
        for exotic in (NBSP, THIN_SPACE, HAIR_SPACE, ZERO_WIDTH_SPACE):
            normalized, _ = normalize_for_detection(f"36{exotic}03")
            assert normalized == "3603"

    def test_soft_hyphen_is_deleted(self) -> None:
        text = f"докумен{SOFT_HYPHEN}т"
        normalized, mapping = normalize_for_detection(text)
        assert normalized == "документ"
        # Мягкий перенос убран без остатка — по количеству буквенных
        # символов нормализованный текст совпадает с исходным без дефиса,
        # а карта смещений это же самое подтверждает по индексам.
        assert normalized == text.replace(SOFT_HYPHEN, "")
        assert mapping[0] == 0 and mapping[-1] == len(text)

    def test_linebreak_inside_a_number_is_glued(self) -> None:
        text = "ИНН 36621\n03003"
        normalized, _ = normalize_for_detection(text)
        assert normalized == f"ИНН {VALID_INN}"

    def test_linebreak_between_sentences_stays_a_separator(self) -> None:
        """Перенос строки на границе слов — обычная граница, не склейка."""
        text = "Пункт 1.\nПункт 2."
        normalized, _ = normalize_for_detection(text)
        assert normalized == "Пункт 1. Пункт 2."

    def test_latin_homoglyphs_are_folded_to_cyrillic(self) -> None:
        # "H" латиница вместо "Н" кириллицы — частый артефакт копипаста из
        # PDF/сканов, визуально неотличимый в большинстве шрифтов.
        mixed = "HНН " + VALID_INN  # H (латиница) + НН (кириллица)
        normalized, _ = normalize_for_detection(mixed)
        assert normalized == f"ННН {VALID_INN}"

    def test_spacing_glues_single_char_run_of_letters_and_digits(self) -> None:
        text = "И Н Н   3 6 6 2 1 0 3 0 0 3"
        normalized, _ = normalize_for_detection(text)
        assert normalized == f"ИНН {VALID_INN}"

    def test_spacing_does_not_touch_ordinary_short_words(self) -> None:
        """Разрядка ловит только заглавные одиночные токены — не «я и в»."""
        text = "я и в доме"
        normalized, _ = normalize_for_detection(text)
        assert normalized == text

    def test_label_glued_to_digits_gets_a_boundary_space(self) -> None:
        text = f"(ИНН{VALID_INN})"
        normalized, _ = normalize_for_detection(text)
        assert normalized == f"(ИНН {VALID_INN})"

    def test_label_split_does_not_touch_unrelated_letters_and_digits(self) -> None:
        """Список меток закрыт — обычное слово перед числом не трогаем."""
        text = "квартира24"
        normalized, _ = normalize_for_detection(text)
        assert normalized == text

    def test_pure_latin_website_is_not_mangled_by_homoglyph_folding(self) -> None:
        """Регрессия: гомоглифы не должны трогать токен без единой
        кириллической буквы — `www`/`triema`/`ru` целиком латинские."""
        text = "www.triema.ru"
        normalized, _ = normalize_for_detection(text)
        assert normalized == text

    def test_pure_latin_url_with_scheme_and_path_is_not_mangled(self) -> None:
        text = "https://triema.ru/catalog"
        normalized, _ = normalize_for_detection(text)
        assert normalized == text

    def test_pure_latin_email_is_not_mangled(self) -> None:
        text = "info@triema.ru"
        normalized, _ = normalize_for_detection(text)
        assert normalized == text

    def test_pure_latin_product_code_is_not_mangled(self) -> None:
        text = "арт. MLT-0.25"
        normalized, _ = normalize_for_detection(text)
        assert normalized == text

    def test_cyrillic_text_with_ambiguous_looking_letters_is_not_mangled(self) -> None:
        """«ГОСТ», «Р» набраны настоящей кириллицей — гомоглифы это не
        трогают вообще (ключи `_HOMOGLYPHS` — латинские символы)."""
        text = "ГОСТ Р 51141-98"
        normalized, _ = normalize_for_detection(text)
        assert normalized == text

    def test_homoglyph_folding_only_applies_inside_a_mixed_token(self) -> None:
        """«ИHН» — смешанный токен (кириллица И/Н + латинская H): гомоглиф
        внутри него по-прежнему чинится, регрессия это не должна убить."""
        mixed = f"ИHН {VALID_INN}"
        normalized, _ = normalize_for_detection(mixed)
        assert normalized == f"ИНН {VALID_INN}"


class TestDetectAgentAcceptsLayoutVariants:
    """Пять приёмочных кейсов Р1 — сквозь настоящий `DetectAgent`."""

    def test_spaced_out_letters_and_digits(self) -> None:
        text = "И Н Н   3 6 6 2 1 0 3 0 0 3"
        found = _detect_inn(text)
        # Найденная сущность — только тело номера (метка «И Н Н» в неё не
        # входит, как и у обычного «ИНН 3662103003»), но обратно на
        # исходный текст оно отображается вместе со своими пробелами —
        # ровно как они стоят в документе.
        assert found == [text[text.index("3") :]]

    def test_linebreak_inside_the_number(self) -> None:
        text = "ИНН 36621\n03003"
        found = _detect_inn(text)
        assert found == ["36621\n03003"]

    def test_nbsp_grouping_inside_the_number(self) -> None:
        text = f"ИНН{NBSP}3662{NBSP}103003"
        found = _detect_inn(text)
        assert found == [f"3662{NBSP}103003"]

    def test_soft_hyphen_inside_the_number(self) -> None:
        text = f"ИНН 36621{SOFT_HYPHEN}03003"
        found = _detect_inn(text)
        assert found == [f"36621{SOFT_HYPHEN}03003"]

    def test_label_glued_directly_to_digits(self) -> None:
        text = f"(ИНН{VALID_INN})"
        found = _detect_inn(text)
        assert found == [VALID_INN]

    def test_double_space_in_a_real_name_keeps_original_bytes(self) -> None:
        text = "Приказом назначена ответственной Гуляева Татьяны  Ивановны, паспорт."
        result = DetectAgent(default_detectors()).detect(_document(text))
        persons = [entity for entity in result.entities if entity.type == EntityType.PERSON]
        assert persons, "персона не найдена"
        entity = persons[0]
        # Инвариант DetectAgent._validate: текст сущности обязан посимвольно
        # совпадать со срезом ИСХОДНОГО сегмента — включая двойной пробел.
        assert entity.text == text[entity.start : entity.end]
        assert "  " in entity.text
        assert entity.text == "Гуляева Татьяны  Ивановны"

    def test_website_and_email_are_not_detected_as_inn_after_homoglyph_folding(self) -> None:
        """Регрессия: до фикса `triema` внутри `www.triema.ru` частично
        подменялся кириллицей, и это ломало детекторы сайта/e-mail выше по
        пайплайну. Здесь проверяем именно то, что нормализация ИНН не
        зависит от присутствия рядом чисто латинских токенов."""
        text = "www.triema.ru ИНН 3662103003"
        found = _detect_inn(text)
        assert found == ["3662103003"]

    def test_latin_h_glued_to_cyrillic_inn_label_is_still_detected(self) -> None:
        text = f"ИHН {VALID_INN}"
        found = _detect_inn(text)
        assert found == [VALID_INN]

    def test_run_is_idempotent_on_already_masked_style_text(self) -> None:
        """Повторный прогон нормализации не должен ничего сломать —
        обычный однопробельный текст остаётся собой (детерминизм, Р1)."""
        text = "ИНН 3662103003, КПП 366201001"
        normalized_once, _ = normalize_for_detection(text)
        normalized_twice, _ = normalize_for_detection(normalized_once)
        assert normalized_once == normalized_twice == text

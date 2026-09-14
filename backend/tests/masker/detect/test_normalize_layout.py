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


def _detect_type(text: str, entity_type: EntityType) -> list[str]:
    """Вернуть исходные спаны одного типа из сквозной детекции."""
    result = DetectAgent(default_detectors()).detect(_document(text))
    return [entity.text for entity in result.entities if entity.type == entity_type]


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

    def test_glued_kpp_inn_splits_when_label_is_directly_before(self) -> None:
        """Метка сразу перед слипшимся хвостом — обычный случай ячейки таблицы."""
        text = f"Реквизиты: ИНН/КПП 595911001{VALID_INN}."
        normalized, _ = normalize_for_detection(text)
        assert normalized == f"Реквизиты: ИНН/КПП 595911001 {VALID_INN}."

    def test_glued_digit_run_far_from_kpp_inn_label_is_not_split(self) -> None:
        """Совпадение контрольной суммы ИНН на чужом числе — не повод резать.

        14.09.2026, `ipklh-2022-01-11.pdf`: «ИНН/КПП» party'и стоит в начале
        сегмента, а за ~200 символов дальше — 20-значный «Единый
        казначейский счёт», чей случайный хвост из 10 цифр прошёл проверку
        контрольной суммы ИНН. Метка где-то в сегменте (старая проверка)
        резала счёт пополам и подсовывала профилю стороны чужой ИНН
        казначейства. Метка обязана стоять рядом (`_KPP_INN_LABEL_WINDOW`),
        иначе слипшийся хвост остаётся целым 19-значным числом — детектор
        ИНН его не видит (нет границы не-цифры с обеих сторон)."""
        kpp_like_prefix = "595911001"
        filler = "х" * 50
        text = (
            "ИНН присвоен по месту постановки на учет."
            f"{filler} Казначейский счет {kpp_like_prefix}{VALID_INN}."
        )
        normalized, _ = normalize_for_detection(text)
        assert normalized == text
        assert VALID_INN not in _detect_inn(text)

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

    def test_sparse_segment_is_collapsed_but_title_case_name_keeps_word_boundaries(self) -> None:
        """Разрядка всего сегмента не мешает NER увидеть отдельные части ФИО."""
        text = "М а г о м е д о в А б д у р а х м а н Ю н у с о в и ч"
        normalized, mapping = normalize_for_detection(text)
        assert normalized == "Магомедов Абдурахман Юнусович"
        start = normalized.index("Магомедов")
        assert _map_roundtrip(text, mapping, start, len(normalized)) == text

    def test_sparse_account_chain_is_split_only_after_account_label(self) -> None:
        """Два слипшихся счета остаются двумя 20-разрядными кандидатами."""
        text = "Р а с ч е т н ы й с ч е т 4070281096032001443403224643820000000300"
        normalized, mapping = normalize_for_detection(text)
        assert normalized == "Расчетныйсчет 40702810960320014434 03224643820000000300"
        first = normalized.index("40702810960320014434")
        second = normalized.index("03224643820000000300")
        assert _map_roundtrip(text, mapping, first, first + 20) == "40702810960320014434"
        assert _map_roundtrip(text, mapping, second, second + 20) == "03224643820000000300"

    def test_sparse_correspondent_account_chain_is_split_after_short_label(self) -> None:
        text = "К о р р . с ч е т 3010181090702000061540102810945370000069"
        normalized, _ = normalize_for_detection(text)
        assert normalized == "Корр . счет 30101810907020000615 40102810945370000069"

    def test_sparse_kpp_and_inn_chain_is_split_at_valid_inn(self) -> None:
        text = "И Н Н / К П П 0 5 5 4 0 1 0 0 1 0 5 4 5 0 1 1 6 2 8"
        normalized, _ = normalize_for_detection(text)
        assert normalized == "ИНН / КПП 055401001 0545011628"

    def test_sparse_phone_chain_repairs_text_layer_and_splits_numbers(self) -> None:
        text = "Т е л е ф о н ы 8 - 9 2 8 - 5 6 5 - 4 f - 3 1 8 -9 0 3 - 4 8 0 - 0 8 - 6 2"
        normalized, mapping = normalize_for_detection(text)
        assert normalized == "Телефоны 8-928-565-41-31,8-903-480-08-62"
        second = normalized.index("8-903")
        assert _map_roundtrip(text, mapping, second, second + len("8-903-480-08-62")) == (
            "8 -9 0 3 - 4 8 0 - 0 8 - 6 2"
        )

    def test_sparse_email_chain_repairs_ocr_symbols_and_keeps_three_spans(self) -> None:
        text = (
            "Е - m ail k tk -d a 2 ® .m a il.r u : "
            "k a sp iy te le k o m f® ,m a il.r u k a s o k o lle ® ,m a il.r u"
        )
        normalized, _ = normalize_for_detection(text)
        assert normalized == "Е-mail ktk-da2@mail.ru : kaspiytelekomf@mail.ru kasokolle@mail.ru"
        assert _detect_type(text, EntityType.EMAIL) == [
            "k tk -d a 2 ® .m a il.r u",
            "k a sp iy te le k o m f® ,m a il.r u ",
            "k a s o k o lle ® ,m a il.r u",
        ]

    def test_concatenated_biks_are_separate_labeled_values(self) -> None:
        text = "БИК040702615018209001"
        normalized, _ = normalize_for_detection(text)
        assert normalized == "БИК 040702615 БИК 018209001"
        assert _detect_type(text, EntityType.BIK) == ["040702615", "018209001"]

    def test_sparse_signatory_initials_include_the_final_dot_in_source_span(self) -> None:
        text = "М а г о м е д о в Н .Г ."
        assert _detect_type(text, EntityType.PERSON) == [text]

    def test_sparse_gbpou_name_is_detected_as_organization(self) -> None:
        text = "Г Б П О У Р Д я К А и С »"
        assert _detect_type(text, EntityType.ORG_NAME) == [text]

    def test_columnar_requisites_keep_digit_to_letter_boundaries(self) -> None:
        """Двойные пробелы обычной таблицы не должны склеивать реквизиты.

        Регрессия `arkhschool-68-183.pdf`, сегмент 197: там 5 одиночных
        буквенных токенов из 50, то есть это колоночная вёрстка, а не
        разрядка. Без границ после чисел терялись ОГРН, оба счёта и ОКПО.
        """
        text = (
            "Код отрасли по ОКПО: 17514186  ОГРН: 1027700198767  "
            "БАНК: ПАО Сбербанк  БИК: 0044525225 "
            "Корреспондентский счет:  30101810400000000225  "
            "Расчетный счет: 40702810038180132605"
        )
        normalized, _ = normalize_for_detection(text)
        assert "1027700198767 БАНК" in normalized
        assert "30101810400000000225 Расчетный" in normalized
        assert _detect_type(text, EntityType.OGRN) == ["1027700198767"]
        assert _detect_type(text, EntityType.BANK_ACCOUNT) == [
            "30101810400000000225",
            "40702810038180132605",
        ]
        assert _detect_type(text, EntityType.REGISTRY_KEY) == ["17514186"]

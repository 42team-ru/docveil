from pathlib import Path

from masker.detect.agent import DetectAgent
from masker.ingest.docx_ingest import ingest_docx
from masker.model import Anchor, Entity, EntityType, Segment, Source
from masker.profile.blocks import build_context_blocks

FIXTURES = Path(__file__).parents[3] / "fixtures" / "labeled"


def _segment(order: int, text: str) -> Segment:
    return Segment(text, Anchor("docx", ("body", order)), order)


def test_label_does_not_survive_section_heading() -> None:
    """Метка преамбулы не должна наследоваться пунктами договора после заголовка.

    В реальном документе метка «покупатель» бралась из преамбулы и наследовалась
    пунктом 1.3, где на самом деле назван банкрот-продавец имущества, а не
    покупатель — заголовок обязан гасить метку.
    """
    segments = [
        _segment(0, "____, именуем__ в дальнейшем «Покупатель», с другой стороны"),
        _segment(1, "1. Предмет договора"),
        _segment(2, "1.3. Продажа имущества ООО «Мойдодыр»"),
    ]
    mojdodyr_start = segments[2].text.index("ООО «Мойдодыр»")
    mojdodyr_end = mojdodyr_start + len("ООО «Мойдодыр»")
    entities = [
        Entity(
            EntityType.ORG_NAME,
            "ООО «Мойдодыр»",
            2,
            mojdodyr_start,
            mojdodyr_end,
            Source.RULE,
            0.9,
            "мойдодыр",
        )
    ]

    blocks = build_context_blocks(segments, entities)

    mojdodyr_block = next(block for block in blocks if block.entities)
    assert mojdodyr_block.label == ""


def test_label_still_applies_when_heading_carries_it() -> None:
    """Заголовок, который сам несёт метку («1. Реквизиты Поставщика»), обязан её выставить."""
    segments = [
        _segment(0, "1. Реквизиты Поставщика"),
        _segment(1, "ООО «Ромашка», ИНН 7701234567"),
    ]
    inn_start = segments[1].text.index("7701234567")
    entities = [
        Entity(
            EntityType.INN,
            "7701234567",
            1,
            inn_start,
            inn_start + len("7701234567"),
            Source.RULE,
            0.9,
            "7701234567",
        )
    ]

    blocks = build_context_blocks(segments, entities)

    assert [block.label for block in blocks if block.entities] == ["поставщика"]


def test_label_reset_on_anchor_kind_change() -> None:
    """Смена типа якоря (например, тело → таблица) тоже гасит унаследованную метку."""
    segments = [
        Segment(
            "____, именуем__ в дальнейшем «Продавец», с одной стороны",
            Anchor("docx", ("body", 0)),
            0,
        ),
        Segment("ИНН должника-банкрота", Anchor("docx", ("table", 0, 0, 0, 0)), 1),
    ]
    entities = [Entity(EntityType.INN, "7701234567", 1, 0, 10, Source.RULE, 0.9, "7701234567")]

    blocks = build_context_blocks(segments, entities)

    label_block = next(block for block in blocks if block.entities)
    assert label_block.label == ""


def test_label_change_starts_a_new_block_without_rewriting_existing_entities() -> None:
    """Поздняя метка не присваивается сущности из предыдущего сегмента."""
    segments = [
        _segment(0, "ООО «До метки»"),
        _segment(1, "ООО «Заказчик», именуемое в дальнейшем «Заказчик»"),
    ]
    entities = [
        Entity(EntityType.ORG_NAME, "ООО «До метки»", 0, 0, 15, Source.RULE, 0.9, "до метки"),
        Entity(EntityType.ORG_NAME, "ООО «Заказчик»", 1, 0, 15, Source.RULE, 0.9, "заказчик"),
    ]

    blocks = build_context_blocks(segments, entities)

    assert [(block.label, [entity.text for entity in block.entities]) for block in blocks] == [
        ("", ["ООО «До метки»"]),
        ("заказчик", ["ООО «Заказчик»"]),
    ]


def test_contract_01_blocks_keep_labels_on_own_heading() -> None:
    """Регресс: блоки с меткой на собственном открывающем сегменте не теряют её."""
    document = ingest_docx(FIXTURES / "contract_01.docx")
    entities = DetectAgent().detect(document).entities

    blocks = build_context_blocks(document.segments, entities)

    labeled = {block.id: block.label for block in blocks if block.entities}
    assert labeled == {
        # "ДОГОВОР ПОСТАВКИ № 44/2026" (сегмент 0) — план T2.2.1, шаг 10:
        # contract_number раньше не детектировался вовсе, блок B1 был без
        # сущностей и в этот словарь не попадал.
        "B1": "",
        "B2": "поставщик",
        "B3": "покупатель",
        "B4": "поставщик",
        "B5": "покупатель",
        "B9": "поставщик",
        "B10": "покупатель",
    }

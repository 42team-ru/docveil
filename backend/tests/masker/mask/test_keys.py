from masker.mask.keys import group_key
from masker.model import Entity, EntityType, Source


def _entity(entity_type: EntityType, text: str) -> Entity:
    return Entity(
        type=entity_type,
        text=text,
        segment_order=0,
        start=0,
        end=len(text),
        source=Source.RULE,
    )


def test_three_spellings_of_one_org_share_key() -> None:
    keys = {
        group_key(_entity(EntityType.ORG_NAME, spelling))
        for spelling in ('ООО "Ромашка"', "ООО «Ромашка»", "Ромашка")
    }
    assert len(keys) == 1


def test_inn_with_spaces_and_nbsp_share_key() -> None:
    nbsp = " "
    plain = group_key(_entity(EntityType.INN, "3662103003"))
    spaced = group_key(_entity(EntityType.INN, "3662 103 003"))
    with_nbsp = group_key(_entity(EntityType.INN, f"3662{nbsp}103{nbsp}003"))
    assert plain == spaced == with_nbsp


def test_empty_normalization_does_not_merge_distinct_orgs() -> None:
    """Ловушка `_normalize_org("ООО") == ""`: без спецобработки два разных
    юрлица, от которых в тексте осталась только форма, склеились бы в одну
    группу и получили бы один маркер — прямое нарушение согласованности."""
    ooo_key = group_key(_entity(EntityType.ORG_NAME, "ООО"))
    ao_key = group_key(_entity(EntityType.ORG_NAME, "АО"))
    assert ooo_key != ao_key


def test_key_includes_type() -> None:
    inn_key = group_key(_entity(EntityType.INN, "3662103003"))
    kpp_key = group_key(_entity(EntityType.KPP, "3662103003"))
    assert inn_key != kpp_key

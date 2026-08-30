from masker.model import CRITICAL_TYPES, EntityType, is_critical


def test_criticality_has_one_source_of_truth() -> None:
    assert is_critical(EntityType.INN)
    assert not is_critical(EntityType.PHONE)
    assert {kind for kind in EntityType if is_critical(kind)} == CRITICAL_TYPES

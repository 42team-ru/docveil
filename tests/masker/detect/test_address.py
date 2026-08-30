from __future__ import annotations

from masker.detect.address import address_markers


def test_address_markers_are_sorted_and_cached() -> None:
    address_markers.cache_clear()

    markers = address_markers()

    assert markers is address_markers()
    assert len(markers.street) > 10
    assert markers.street == tuple(
        sorted(markers.street, key=lambda value: (-len(value), value.casefold()))
    )

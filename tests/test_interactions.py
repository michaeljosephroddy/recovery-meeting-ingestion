from app.scraping.interactions import _button_selectors, _search_seed_for_source
from app.sources.registry import Source, SourceType


def test_search_seed_uses_region_first() -> None:
    source = Source(
        id="aa-region",
        fellowship="aa",
        name="Region Source",
        url="https://example.org",
        region="Dublin",
        source_type=SourceType.LOCAL_SERVICE_BODY,
    )

    assert _search_seed_for_source(source) == "Dublin"


def test_search_seed_extracts_city_like_text_from_source_metadata_address() -> None:
    source = Source(
        id="aa-address",
        fellowship="aa",
        name="Address Source",
        url="https://example.org",
        country="Belize",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        config={"metadata": {"address_text": "114 Cemetery Road Belize City Belize"}},
    )

    assert _search_seed_for_source(source) == "Belize City"


def test_heuristic_button_selectors_do_not_click_navigation_anchors() -> None:
    selectors = _button_selectors()

    assert "[aria-expanded='false']" not in selectors
    assert "button[aria-expanded='false']" in selectors
    assert "[role='button'][aria-expanded='false']" in selectors

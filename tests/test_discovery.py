from app.config import Settings
from app.sources.aa_world_services import AaWorldServicesDiscovery
from app.sources.ca_world_services import CA_WORLD_URL, CaWorldServicesDiscovery
from app.sources.na_world_services import (
    NA_WORLD_URL,
    NaWorldServicesDiscovery,
    parse_location_index,
)

from .conftest import FIXTURES


def test_aa_world_fixture_produces_source_candidates_not_meetings() -> None:
    discovery = AaWorldServicesDiscovery(Settings())
    candidates = discovery.parse_html((FIXTURES / "aa_world.html").read_text())

    assert {candidate.fellowship for candidate in candidates} == {"aa"}
    assert len(candidates) == 4
    assert any(str(candidate.url) == "http://www.aadavis.org" for candidate in candidates)
    assert any(str(candidate.url) == "tel:9096284428" for candidate in candidates)
    assert any(candidate.country == "Ireland" for candidate in candidates)
    assert all(not hasattr(candidate, "occurrences") for candidate in candidates)


def test_ca_world_fixture_produces_ca_source_candidates() -> None:
    discovery = CaWorldServicesDiscovery(Settings())
    candidates = discovery.parse_html((FIXTURES / "ca_world.html").read_text())

    assert {candidate.fellowship for candidate in candidates} == {"ca"}
    assert len(candidates) == 2
    assert {candidate.source_type for candidate in candidates} == {"world_service_listing"}


def test_ca_country_fixture_produces_local_source_candidates() -> None:
    discovery = CaWorldServicesDiscovery(Settings())
    candidates = discovery.parse_html_for_url(
        (FIXTURES / "ca_ireland.html").read_text(),
        "https://ca.org/meetings/ireland/",
    )

    assert len(candidates) == 1
    assert candidates[0].fellowship == "ca"
    assert str(candidates[0].url) == "https://www.caireland.live"
    assert candidates[0].country == "Ireland"


def test_na_world_fixture_produces_na_source_candidates() -> None:
    discovery = NaWorldServicesDiscovery(Settings())
    payload = (FIXTURES / "na_locator.json").read_text()
    candidates = discovery.parse_html(payload)

    assert {candidate.fellowship for candidate in candidates} == {"na"}
    assert len(candidates) == 2
    assert str(candidates[0].url) == "https://www.na-ireland.org/na-meetings/east/"
    assert str(candidates[1].url) == "tel:+18334366166"
    assert candidates[1].source_type == "phone"


def test_na_locator_payload_produces_seed_locations() -> None:
    locations = parse_location_index((FIXTURES / "na_locator.json").read_text())

    assert locations == [
        {"country": "United States", "state": "New York"},
        {"country": "Canada", "state": "Ontario"},
        {"country": "Ireland", "state": ""},
    ]


def test_world_service_default_urls_match_official_pages() -> None:
    assert NA_WORLD_URL == "https://na.org/meetingsearch/find-na/"
    assert CA_WORLD_URL == "https://ca.org/meetings/"

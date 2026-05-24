from app.sources.registry import (
    SourceCandidate,
    normalize_source_url,
    source_from_candidate,
    source_id_for_candidate,
    timezone_for_country_region,
    timezone_for_source_text,
)


def test_normalize_source_url_is_stable() -> None:
    assert (
        normalize_source_url("HTTPS://Example.ORG/path/?b=2&a=1#fragment")
        == "https://example.org/path?a=1&b=2"
    )
    assert normalize_source_url("https://example.org/path/") == "https://example.org/path"


def test_source_from_candidate_has_stable_id_and_normalized_url() -> None:
    candidate = SourceCandidate(
        fellowship="aa",
        label="Example Intergroup",
        url="https://Example.org/meetings/?b=2&a=1",
        country="US",
    )
    source = source_from_candidate(candidate)

    assert source.id == source_id_for_candidate(candidate)
    assert source.id.startswith("aa-")
    assert source.name == "Example Intergroup"
    assert source.normalized_url == "https://example.org/meetings?a=1&b=2"


def test_source_from_candidate_infers_timezone_from_region() -> None:
    source = source_from_candidate(
        SourceCandidate(
            fellowship="ca",
            label="Arizona",
            url="https://caarizona.example/",
            country="United States",
            region="Arizona",
        )
    )

    assert source.config["timezone"] == "America/Phoenix"


def test_source_from_candidate_infers_region_and_timezone_from_label() -> None:
    source = source_from_candidate(
        SourceCandidate(
            fellowship="ca",
            label="California - Northern",
            url="https://canorcal.example/",
            country="United States",
        )
    )

    assert source.region == "California"
    assert source.config["timezone"] == "America/Los_Angeles"


def test_source_from_candidate_infers_single_timezone_country() -> None:
    source = source_from_candidate(
        SourceCandidate(
            fellowship="ca",
            label="Ireland",
            url="https://caireland.example/",
            country="Ireland",
        )
    )

    assert source.config["timezone"] == "Europe/Dublin"


def test_timezone_for_country_region_handles_australian_state_abbreviation() -> None:
    assert timezone_for_country_region("Australia", "WA") == "Australia/Perth"


def test_timezone_for_country_region_handles_brazil_region_abbreviation() -> None:
    assert timezone_for_country_region("Brazil", "SP") == "America/Sao_Paulo"


def test_timezone_for_country_region_handles_canadian_province_abbreviation() -> None:
    assert timezone_for_country_region("Canada", "QC") == "America/Toronto"


def test_timezone_for_country_region_handles_mexican_state() -> None:
    assert timezone_for_country_region("Mexico", "Jalisco") == "America/Mexico_City"
    assert timezone_for_country_region("Mexico", "Quintana Roo") == "America/Cancun"
    assert timezone_for_country_region("Mexico", "Sinaloa") == "America/Mazatlan"


def test_timezone_for_country_region_handles_city_hint_without_country() -> None:
    assert timezone_for_country_region(None, "Geneva") == "Europe/Zurich"


def test_timezone_for_source_text_handles_clear_single_region_sources() -> None:
    assert timezone_for_source_text("Cyprus Intergroup", "https://example.org") == "Asia/Nicosia"
    assert (
        timezone_for_source_text("Port Of Spain Intergroup Of A.A.", "https://example.org")
        == "America/Port_of_Spain"
    )
    assert timezone_for_source_text("District 35 Area 78", "http://aayellowknife.ca") == (
        "America/Yellowknife"
    )
    assert (
        timezone_for_source_text("Kingston Jamaica Answering Service", "https://example.org")
        == "America/Jamaica"
    )

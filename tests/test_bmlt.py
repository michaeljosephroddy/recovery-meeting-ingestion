import json

import httpx

from app.adapters.bmlt import BmltAdapter
from app.sources.registry import AdapterType, Source, SourceType

from .conftest import FIXTURES


def test_bmlt_fixture_normalizes_stable_source_id_and_location() -> None:
    source = Source(
        id="na-ie-bmlt",
        fellowship="na",
        name="NA Ireland BMLT",
        url="https://bmlt.example.org/main_server",
        country="IE",
        source_type=SourceType.MEETING_FEED,
        adapter_type=AdapterType.BMLT,
    )
    adapter = BmltAdapter(source, user_agent="test")
    raw = adapter.raw_records_from_payload(json.loads((FIXTURES / "bmlt.json").read_text()))[0]
    candidate = adapter.normalize(raw)

    assert candidate.source_record_id == "1001"
    assert candidate.name == "Hope Group"
    assert candidate.city == "Cork"
    assert candidate.latitude == 51.8985
    assert candidate.longitude == -8.4756
    assert candidate.occurrences[0].day_of_week == 2


def test_bmlt_adapter_infers_timezone_from_country_and_region() -> None:
    source = Source(
        id="na-au-bmlt",
        fellowship="na",
        name="NA Australia BMLT",
        url="https://bmlt.example.org/main_server",
        country="Australia",
        source_type=SourceType.MEETING_FEED,
        adapter_type=AdapterType.BMLT,
    )
    adapter = BmltAdapter(source, user_agent="test")
    raw = adapter.raw_records_from_payload(
        [
            {
                "id_bigint": "1002",
                "meeting_name": "Sydney Group",
                "weekday_tinyint": "3",
                "start_time": "19:00",
                "formatted_address": "1 Recovery Street",
                "location_nation": "AU",
                "location_province": "NSW",
                "time_zone": "UTC",
            }
        ]
    )[0]

    candidate = adapter.normalize(raw)

    assert candidate.occurrences[0].timezone == "Australia/Sydney"


def test_bmlt_adapter_infers_australia_timezone_from_postal_code() -> None:
    source = Source(
        id="na-au-bmlt",
        fellowship="na",
        name="NA Australia BMLT",
        url="https://bmlt.example.org/main_server",
        country="Australia",
        source_type=SourceType.MEETING_FEED,
        adapter_type=AdapterType.BMLT,
    )
    adapter = BmltAdapter(source, user_agent="test")
    raw = adapter.raw_records_from_payload(
        [
            {
                "id_bigint": "1003",
                "meeting_name": "Fremantle Group",
                "weekday_tinyint": "3",
                "start_time": "19:00",
                "formatted_address": "1 Recovery Street",
                "location_postal_code_1": "6160",
            }
        ]
    )[0]

    candidate = adapter.normalize(raw)

    assert candidate.occurrences[0].timezone == "Australia/Perth"


def test_bmlt_adapter_does_not_infer_australia_timezone_for_out_of_country_coordinates() -> None:
    source = Source(
        id="na-au-bmlt",
        fellowship="na",
        name="NA Australia BMLT",
        url="https://bmlt.example.org/main_server",
        country="Australia",
        source_type=SourceType.MEETING_FEED,
        adapter_type=AdapterType.BMLT,
    )
    adapter = BmltAdapter(source, user_agent="test")
    raw = adapter.raw_records_from_payload(
        [
            {
                "id_bigint": "1004",
                "meeting_name": "Online Group",
                "weekday_tinyint": "3",
                "start_time": "19:00",
                "virtual_meeting_link": "https://example.org/meeting",
                "latitude": "36.0686588",
                "longitude": "-94.1759132",
            }
        ]
    )[0]

    candidate = adapter.normalize(raw)

    assert candidate.occurrences[0].timezone == "UTC"


def test_bmlt_adapter_preserves_non_url_virtual_meeting_text() -> None:
    source = Source(
        id="na-fl-bmlt",
        fellowship="na",
        name="NA Florida BMLT",
        url="https://bmlt.example.org/main_server",
        country="US",
        source_type=SourceType.MEETING_FEED,
        adapter_type=AdapterType.BMLT,
    )
    adapter = BmltAdapter(source, user_agent="test")
    raw = adapter.raw_records_from_payload(
        [
            {
                "id_bigint": "8330",
                "meeting_name": "How it Works",
                "weekday_tinyint": "7",
                "start_time": "10:00:00",
                "location_municipality": "Orlando",
                "location_province": "FL",
                "location_nation": "US",
                "virtual_meeting_link": "virtually on zoom - 404031193",
            }
        ]
    )[0]

    candidate = adapter.normalize(raw)

    assert candidate.online_url is None
    assert candidate.phone_join_info == "virtually on zoom - 404031193"
    assert candidate.meeting_type == "online"


async def test_bmlt_fetch_uses_configured_endpoint() -> None:
    source = Source(
        id="na-ie-bmlt",
        fellowship="na",
        name="NA Ireland BMLT",
        url="https://bmlt.example.org/main_server",
        country="IE",
        source_type=SourceType.MEETING_FEED,
        adapter_type=AdapterType.BMLT,
        config={"bmlt_search_endpoint": "https://bmlt.example.org/custom-search"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://bmlt.example.org/custom-search"
        return httpx.Response(
            200,
            json=[
                {
                    "id_bigint": "1001",
                    "meeting_name": "Hope Group",
                    "formatted_address": "2 Main Road",
                }
            ],
        )

    adapter = BmltAdapter(source, user_agent="test", transport=httpx.MockTransport(handler))
    raw_records = await adapter.fetch()

    assert raw_records[0].source_record_id == "1001"

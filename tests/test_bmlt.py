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

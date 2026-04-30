import httpx

from app.adapters.static_html import StaticHtmlAdapter
from app.config import Settings
from app.ingest import ingest_source
from app.sources.registry import AdapterType, Source, SourceType

from .conftest import FIXTURES


def static_source() -> Source:
    return Source(
        id="aa-static",
        fellowship="aa",
        name="Static AA",
        url="https://static.example.org/meetings",
        country="IE",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.STATIC_HTML,
        config={
            "timezone": "Europe/Dublin",
            "selectors": {
                "row": ".meeting",
                "source_record_id": ".meeting::attr(data-id)",
                "name": ".name",
                "day": ".day",
                "time": ".time",
                "venue_name": ".venue",
                "address_line1": ".address",
                "city": ".city",
                "formats": ".formats",
            },
        },
    )


def test_static_html_adapter_parses_configured_selectors() -> None:
    adapter = StaticHtmlAdapter(static_source())
    raw = adapter.raw_records_from_html((FIXTURES / "static_meetings.html").read_text())[0]
    candidate = adapter.normalize(raw)

    assert raw.source_record_id == "monday-main"
    assert candidate.name == "Monday Main"
    assert candidate.address_line1 == "10 Main Street"
    assert candidate.occurrences[0].day_of_week == 1
    assert candidate.occurrences[0].start_time_local.hour == 19
    assert candidate.occurrences[0].timezone == "Europe/Dublin"
    assert candidate.formats == ["Open", "Discussion"]


async def test_static_html_adapter_fetch_uses_transport() -> None:
    source = static_source()
    adapter = StaticHtmlAdapter(
        source,
        user_agent="test-agent",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text=(FIXTURES / "static_meetings.html").read_text(),
                request=request,
            )
        ),
    )

    raw_records = await adapter.fetch()

    assert len(raw_records) == 1
    assert raw_records[0].source_record_id == "monday-main"


async def test_ingest_source_supports_static_html_fixture() -> None:
    result = await ingest_source(
        static_source(),
        settings=Settings(),
        fixture=FIXTURES / "static_meetings.html",
    )

    assert len(result.raw_records) == 1
    assert result.candidates[0].name == "Monday Main"

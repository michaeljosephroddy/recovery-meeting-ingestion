import httpx

from app.adapters.base import RawMeeting
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


def test_static_html_adapter_infers_timezone_from_payload_region() -> None:
    source = static_source().model_copy(update={"country": "Australia", "config": {}})
    raw = RawMeeting(
        source_id=source.id,
        source_record_id="australia-wa",
        source_url=source.url,
        payload={
            "name": "Perth Monday",
            "day": "Monday",
            "time": "7:00 pm",
            "address_line1": "1 Example Street",
            "region": "WA",
        },
        content_hash="hash",
    )

    candidate = StaticHtmlAdapter(source).normalize(raw)

    assert candidate.occurrences[0].timezone == "Australia/Perth"


def test_static_html_adapter_infers_canada_timezone_from_address() -> None:
    source = static_source().model_copy(update={"country": None, "config": {}})
    raw = RawMeeting(
        source_id=source.id,
        source_record_id="quebec-row",
        source_url=source.url,
        payload={
            "name": "Saint-Jerome Sunday",
            "day": "Sunday",
            "time": "7:00 am",
            "address_line1": "327 Rue Saint-Georges, Saint-Jerome, QC J7Z 5A8, Canada",
            "region": "Saint-Jerome",
        },
        content_hash="hash",
    )

    candidate = StaticHtmlAdapter(source).normalize(raw)

    assert candidate.country == "Canada"
    assert candidate.region == "Saint-Jerome"
    assert candidate.occurrences[0].timezone == "America/Toronto"


def test_static_html_adapter_does_not_treat_on_as_ontario_outside_canada() -> None:
    source = static_source().model_copy(update={"country": "Ireland", "config": {}})
    raw = RawMeeting(
        source_id=source.id,
        source_record_id="ireland-on-word",
        source_url=source.url,
        payload={
            "name": "C.A. Nenagh",
            "day": "Friday",
            "time": "7:00 pm",
            "address_line1": (
                "Open Meeting to family, friends and other interested people "
                "on the 2nd Friday of March"
            ),
            "region": "Co. Tipperary",
            "timezone": "UTC",
        },
        content_hash="hash",
    )

    candidate = StaticHtmlAdapter(source).normalize(raw)

    assert candidate.country == "Ireland"
    assert candidate.region == "Co. Tipperary"
    assert candidate.occurrences[0].timezone == "Europe/Dublin"


def test_static_html_adapter_infers_mexico_timezone_from_address_and_region() -> None:
    source = static_source().model_copy(update={"country": None, "config": {}})
    raw = RawMeeting(
        source_id=source.id,
        source_record_id="mexico-row",
        source_url=source.url,
        payload={
            "name": "Puerto Vallarta Sunday",
            "day": "Sunday",
            "time": "9:00 am",
            "address_line1": "Libertad 105, Centro, 48300 Puerto Vallarta, Jal., Mexico",
            "region": "Jalisco",
            "timezone": "UTC",
        },
        content_hash="hash",
    )

    candidate = StaticHtmlAdapter(source).normalize(raw)

    assert candidate.country == "Mexico"
    assert candidate.region == "Jalisco"
    assert candidate.occurrences[0].timezone == "America/Mexico_City"


def test_static_html_adapter_infers_us_timezone_from_address() -> None:
    source = static_source().model_copy(update={"country": None, "config": {}})
    raw = RawMeeting(
        source_id=source.id,
        source_record_id="new-york-row",
        source_url=source.url,
        payload={
            "name": "Honesty Group",
            "day": "Tuesday",
            "time": "7:00 pm",
            "address_line1": "4897a NY-56, Colton, NY 13625, USA",
            "region": "Eastern Ontario 83",
            "timezone": "UTC",
        },
        content_hash="hash",
    )

    candidate = StaticHtmlAdapter(source).normalize(raw)

    assert candidate.country == "United States"
    assert candidate.region == "Eastern Ontario 83"
    assert candidate.occurrences[0].timezone == "America/New_York"


def test_static_html_adapter_uses_source_country_hint_for_state_abbreviation() -> None:
    source = static_source().model_copy(update={"country": "United States", "config": {}})
    raw = RawMeeting(
        source_id=source.id,
        source_record_id="ohio-row",
        source_url=source.url,
        payload={
            "name": "Cleveland Friday",
            "day": "Friday",
            "time": "6:00 pm",
            "address_line1": "2554 West 25th St., Cleveland, OH",
            "timezone": "UTC",
        },
        content_hash="hash",
    )

    candidate = StaticHtmlAdapter(source).normalize(raw)

    assert candidate.country == "United States"
    assert candidate.region == "Ohio"
    assert candidate.occurrences[0].timezone == "America/New_York"


def test_static_html_adapter_uses_source_country_hint_for_australian_state() -> None:
    source = static_source().model_copy(update={"country": "Australia", "config": {}})
    raw = RawMeeting(
        source_id=source.id,
        source_record_id="nsw-row",
        source_url=source.url,
        payload={
            "name": "Bondi Friday",
            "day": "Friday",
            "time": "8:00 pm",
            "address_line1": "138 Bondi Rd, Bondi, NSW",
            "timezone": "UTC",
        },
        content_hash="hash",
    )

    candidate = StaticHtmlAdapter(source).normalize(raw)

    assert candidate.country == "Australia"
    assert candidate.region == "Nsw"
    assert candidate.occurrences[0].timezone == "Australia/Sydney"


def test_static_html_adapter_prefers_address_country_over_source_country() -> None:
    source = static_source().model_copy(
        update={
            "country": "Poland",
            "region": "Wielka Brytania",
            "config": {"timezone": "Europe/Warsaw"},
        }
    )
    raw = RawMeeting(
        source_id=source.id,
        source_record_id="polish-london-row",
        source_url=source.url,
        payload={
            "name": "ACTION ACTION ACTION",
            "day": "Monday",
            "time": "7:00 pm",
            "venue_name": "Londyn",
            "address_line1": "2 Windsor Rd, London W5 5PD, Wielka Brytania",
        },
        content_hash="hash",
    )

    candidate = StaticHtmlAdapter(source).normalize(raw)

    assert candidate.country == "United Kingdom"
    assert candidate.city == "London"
    assert candidate.region is None
    assert candidate.occurrences[0].timezone == "Europe/London"


def test_static_html_adapter_does_not_infer_london_from_street_name() -> None:
    source = static_source().model_copy(
        update={
            "country": "Poland",
            "region": "Wielka Brytania",
            "config": {"timezone": "Europe/Warsaw"},
        }
    )
    raw = RawMeeting(
        source_id=source.id,
        source_record_id="chelmsford-row",
        source_url=source.url,
        payload={
            "name": "Przyjaciele Billa",
            "day": "Sunday",
            "time": "6:00 pm",
            "venue_name": "Chelmsford",
            "address_line1": "107 New London Rd, Chelmsford CM2 0PP, Wielka Brytania",
        },
        content_hash="hash",
    )

    candidate = StaticHtmlAdapter(source).normalize(raw)

    assert candidate.country == "United Kingdom"
    assert candidate.city is None
    assert candidate.occurrences[0].timezone == "Europe/London"


def test_static_html_adapter_address_country_override_is_global() -> None:
    source = static_source().model_copy(
        update={
            "country": "United States",
            "region": "New York",
            "config": {"timezone": "America/New_York"},
        }
    )
    raw = RawMeeting(
        source_id=source.id,
        source_record_id="paris-row",
        source_url=source.url,
        payload={
            "name": "Paris Recovery",
            "day": "Tuesday",
            "time": "8:00 pm",
            "address_line1": "12 Rue de Rivoli, Paris, France",
        },
        content_hash="hash",
    )

    candidate = StaticHtmlAdapter(source).normalize(raw)

    assert candidate.country == "France"
    assert candidate.occurrences[0].timezone == "Europe/Paris"


def test_static_html_adapter_infers_united_kingdom_from_postcode() -> None:
    source = static_source().model_copy(update={"country": None, "config": {}})
    raw = RawMeeting(
        source_id=source.id,
        source_record_id="uk-postcode-row",
        source_url=source.url,
        payload={
            "name": "Keep it Real Mondays",
            "day": "Monday",
            "time": "10:30 am",
            "address_line1": "21D Grant St, Inverness IV3 8BN",
            "timezone": "UTC",
        },
        content_hash="hash",
    )

    candidate = StaticHtmlAdapter(source).normalize(raw)

    assert candidate.country == "United Kingdom"
    assert candidate.occurrences[0].timezone == "Europe/London"


def test_static_html_adapter_infers_timezone_from_region_hint() -> None:
    source = static_source().model_copy(update={"country": None, "config": {}})
    raw = RawMeeting(
        source_id=source.id,
        source_record_id="geneva-row",
        source_url=source.url,
        payload={
            "name": "Geneva Sunday",
            "day": "Sunday",
            "time": "9:00 am",
            "address_line1": "Rue du Vieux-Billard 21",
            "region": "Geneva",
        },
        content_hash="hash",
    )

    candidate = StaticHtmlAdapter(source).normalize(raw)

    assert candidate.region == "Geneva"
    assert candidate.occurrences[0].timezone == "Europe/Zurich"


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

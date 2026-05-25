import httpx

from app.adapters.meeting_guide import MeetingGuideAdapter
from app.sources.registry import AdapterType, Source, SourceType
from app.sources.site_classification import SourceProbeClassifier


async def test_classifier_discovers_meeting_guide_feed_from_local_site() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                text='<a href="/wp-json/meeting-guide/v1/meetings">Meetings</a>',
            )
        if request.url.path == "/wp-json/meeting-guide/v1/meetings":
            return httpx.Response(
                200,
                json=[
                    {
                        "slug": "daily-noon",
                        "name": "Daily Noon",
                        "day": "Monday",
                        "time": "12:00",
                    }
                ],
            )
        return httpx.Response(404)

    source = _source("https://local-aa.example/")
    classifier = SourceProbeClassifier(
        user_agent="test",
        transport=httpx.MockTransport(handler),
    )

    result = await classifier.classify(source)

    assert result.source.adapter_type == AdapterType.MEETING_GUIDE
    assert result.source.source_type == SourceType.MEETING_FEED
    assert result.source.requires_browser is False
    assert (
        result.source.config["meeting_guide_feed_url"]
        == "https://local-aa.example/wp-json/meeting-guide/v1/meetings"
    )


async def test_classifier_discovers_bmlt_endpoint_from_local_site() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, text='<a href="/main_server">Meeting Search</a>')
        if request.url.path == "/main_server/client_interface/json/":
            return httpx.Response(
                200,
                json=[
                    {
                        "id_bigint": "42",
                        "meeting_name": "NA Meeting",
                        "weekday_tinyint": "2",
                        "start_time": "19:30",
                    }
                ],
            )
        return httpx.Response(404)

    source = _source("https://local-na.example/", fellowship="na")
    classifier = SourceProbeClassifier(
        user_agent="test",
        transport=httpx.MockTransport(handler),
    )

    result = await classifier.classify(source)

    assert result.source.adapter_type == AdapterType.BMLT
    assert result.source.source_type == SourceType.MEETING_FEED
    assert result.source.requires_browser is False
    assert result.source.config["bmlt_search_endpoint"].startswith(
        "https://local-na.example/main_server/client_interface/json/"
    )


async def test_classifier_marks_meeting_form_for_browser_scraping() -> None:
    source = _source("https://form-site.example/")
    classifier = SourceProbeClassifier(
        user_agent="test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text='<form action="/search"><input name="meeting_search"></form>',
            )
        ),
    )

    result = await classifier.classify(source)

    assert result.source.adapter_type == AdapterType.PLAYWRIGHT_BROWSER
    assert result.source.requires_browser is True
    assert "form" in result.reason


async def test_classifier_marks_meeting_page_for_browser_scraping() -> None:
    source = _source("https://meeting-page.example/")
    classifier = SourceProbeClassifier(
        user_agent="test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text='<a href="/meetings">Find a Meeting</a>',
            )
        ),
    )

    result = await classifier.classify(source)

    assert result.source.adapter_type == AdapterType.PLAYWRIGHT_BROWSER
    assert result.source.requires_browser is True
    assert "meeting page" in result.reason


def test_meeting_guide_adapter_uses_discovered_feed_url() -> None:
    source = _source(
        "https://local-aa.example/",
        config={"meeting_guide_feed_url": "https://local-aa.example/meetings.json"},
    )

    assert MeetingGuideAdapter(source, user_agent="test").feed_url() == (
        "https://local-aa.example/meetings.json"
    )


def _source(
    url: str,
    *,
    fellowship: str = "aa",
    config: dict[str, object] | None = None,
) -> Source:
    return Source(
        id="source-1",
        fellowship=fellowship,  # type: ignore[arg-type]
        name="Local Source",
        url=url,
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.UNKNOWN,
        config=config or {},
    )

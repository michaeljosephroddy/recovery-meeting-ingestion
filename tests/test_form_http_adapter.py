import httpx

from app.adapters.form_http import FormHttpAdapter
from app.sources.registry import AdapterType, Source, SourceType

from .conftest import FIXTURES


def form_source() -> Source:
    return Source(
        id="aa-form",
        fellowship="aa",
        name="Form AA",
        url="https://form.example.org/search",
        country="IE",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.FORM_HTTP,
        config={
            "request": {
                "method": "POST",
                "url": "https://form.example.org/search",
                "data": {"city": "Dublin"},
            },
            "result_type": "html",
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
            },
        },
    )


async def test_form_http_adapter_submits_configured_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://form.example.org/search"
        assert b"city=Dublin" in request.content
        return httpx.Response(200, text=(FIXTURES / "static_meetings.html").read_text())

    adapter = FormHttpAdapter(
        form_source(),
        user_agent="test-agent",
        transport=httpx.MockTransport(handler),
    )
    raw_records = await adapter.fetch()
    candidate = adapter.normalize(raw_records[0])

    assert raw_records[0].source_record_id == "monday-main"
    assert candidate.name == "Monday Main"


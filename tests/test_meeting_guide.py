import json

import httpx
import pytest

from app.adapters.base import AdapterFetchError, AdapterPayloadError
from app.adapters.meeting_guide import MeetingGuideAdapter
from app.sources.aa_feed_registry import build_meeting_guide_source

from .conftest import FIXTURES


def test_meeting_guide_fixture_normalizes_physical_and_online_meetings() -> None:
    source = build_meeting_guide_source(
        source_id="aa-ie-feed",
        feed_url="https://example.org/meetings.json",
        country="IE",
    )
    adapter = MeetingGuideAdapter(source, user_agent="test")
    raw_records = adapter.raw_records_from_payload(
        json.loads((FIXTURES / "meeting_guide.json").read_text())
    )
    candidates = [adapter.normalize(raw) for raw in raw_records]

    physical = candidates[0]
    online = candidates[1]
    assert physical.source_record_id == "daily-reflection-monday"
    assert physical.meeting_type == "in_person"
    assert physical.address_line1 == "1 Main Street"
    assert physical.occurrences[0].day_of_week == 1
    assert physical.occurrences[0].start_time_local.hour == 19
    assert online.source_record_id == "online-big-book"
    assert online.meeting_type == "online"
    assert str(online.online_url) == "https://zoom.example.org/j/123456789"


async def test_meeting_guide_fetch_uses_user_agent_and_mock_transport() -> None:
    source = build_meeting_guide_source("aa-test", "https://example.org/meetings.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == "test-agent"
        return httpx.Response(200, json=[{"slug": "online", "name": "Online", "conference_url": "https://example.org/j/1"}])

    adapter = MeetingGuideAdapter(
        source,
        user_agent="test-agent",
        transport=httpx.MockTransport(handler),
    )
    raw_records = await adapter.fetch()

    assert len(raw_records) == 1
    assert raw_records[0].source_record_id == "online"


async def test_meeting_guide_fetch_retries_transient_status() -> None:
    source = build_meeting_guide_source("aa-test", "https://example.org/meetings.json")
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(500)
        return httpx.Response(200, json=[{"slug": "online", "name": "Online", "conference_url": "https://example.org/j/1"}])

    adapter = MeetingGuideAdapter(
        source,
        user_agent="test-agent",
        transport=httpx.MockTransport(handler),
    )
    raw_records = await adapter.fetch()

    assert attempts == 2
    assert raw_records[0].source_record_id == "online"


async def test_meeting_guide_fetch_rejects_non_array_payload() -> None:
    source = build_meeting_guide_source("aa-test", "https://example.org/meetings.json")
    adapter = MeetingGuideAdapter(
        source,
        user_agent="test-agent",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"bad": True})),
    )

    with pytest.raises(AdapterPayloadError):
        await adapter.fetch()


async def test_meeting_guide_fetch_wraps_non_retryable_status() -> None:
    source = build_meeting_guide_source("aa-test", "https://example.org/meetings.json")
    adapter = MeetingGuideAdapter(
        source,
        user_agent="test-agent",
        transport=httpx.MockTransport(lambda _request: httpx.Response(404)),
    )

    with pytest.raises(AdapterFetchError):
        await adapter.fetch()

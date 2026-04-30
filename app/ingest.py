import json
from pathlib import Path
from typing import Any

from app.adapters.base import RawMeeting, SourceAdapter
from app.adapters.bmlt import BmltAdapter
from app.adapters.form_http import FormHttpAdapter
from app.adapters.meeting_guide import MeetingGuideAdapter
from app.adapters.pdf import PdfAdapter
from app.adapters.playwright_browser import PlaywrightBrowserAdapter
from app.adapters.static_html import StaticHtmlAdapter
from app.config import Settings
from app.normalize.canonical import CanonicalMeetingCandidate
from app.review.flags import ReviewFlag, flags_for_candidate
from app.sources.registry import AdapterType, Source


class IngestResult:
    def __init__(
        self,
        *,
        raw_records: list[RawMeeting],
        candidates: list[CanonicalMeetingCandidate],
        review_flags: list[ReviewFlag],
    ) -> None:
        self.raw_records = raw_records
        self.candidates = candidates
        self.review_flags = review_flags


async def ingest_source(
    source: Source,
    settings: Settings,
    fixture: Path | None = None,
) -> IngestResult:
    adapter = adapter_for_source(source, settings)
    if fixture is None:
        raw_records = await adapter.fetch()
    else:
        raw_records = _raw_records_from_fixture(adapter, fixture)

    candidates = [adapter.normalize(raw) for raw in raw_records]
    review_flags = [
        flag for candidate in candidates for flag in flags_for_candidate(candidate)
    ]
    return IngestResult(
        raw_records=raw_records,
        candidates=candidates,
        review_flags=review_flags,
    )


def adapter_for_source(source: Source, settings: Settings) -> SourceAdapter:
    if source.adapter_type == AdapterType.MEETING_GUIDE:
        return MeetingGuideAdapter(source, user_agent=settings.user_agent)
    if source.adapter_type == AdapterType.BMLT:
        return BmltAdapter(source, user_agent=settings.user_agent)
    if source.adapter_type == AdapterType.STATIC_HTML:
        return StaticHtmlAdapter(source, user_agent=settings.user_agent)
    if source.adapter_type == AdapterType.FORM_HTTP:
        return FormHttpAdapter(source, user_agent=settings.user_agent)
    if source.adapter_type == AdapterType.PDF:
        return PdfAdapter(source, user_agent=settings.user_agent)
    if source.adapter_type == AdapterType.PLAYWRIGHT_BROWSER:
        return PlaywrightBrowserAdapter(source)
    raise ValueError(f"unsupported adapter for ingest-source: {source.adapter_type}")


def _raw_records_from_fixture(adapter: SourceAdapter, fixture: Path) -> list[RawMeeting]:
    if fixture.suffix.lower() in {".html", ".htm"}:
        return _raw_records_from_html(adapter, fixture.read_text(encoding="utf-8"))
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("ingestion JSON fixture must contain an array")
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError("ingestion JSON fixture array must contain objects")
    return _raw_records_from_payload(adapter, payload)


def _raw_records_from_payload(
    adapter: SourceAdapter,
    payload: list[dict[str, Any]],
) -> list[RawMeeting]:
    if isinstance(adapter, MeetingGuideAdapter | BmltAdapter):
        return adapter.raw_records_from_payload(payload)
    raise ValueError("fixture ingestion is only supported for structured adapters")


def _raw_records_from_html(adapter: SourceAdapter, html: str) -> list[RawMeeting]:
    if isinstance(adapter, StaticHtmlAdapter | FormHttpAdapter | PlaywrightBrowserAdapter):
        return adapter.raw_records_from_html(html)
    raise ValueError("HTML fixture ingestion is only supported for HTML-capable adapters")

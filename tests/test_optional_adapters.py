import pytest

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.adapters.pdf import PdfAdapter
from app.adapters.playwright_browser import PlaywrightBrowserAdapter
from app.sources.registry import AdapterType, Source, SourceType


def pdf_source() -> Source:
    return Source(
        id="aa-pdf",
        fellowship="aa",
        name="PDF AA",
        url="https://pdf.example.org/meetings.pdf",
        source_type=SourceType.PDF,
        adapter_type=AdapterType.PDF,
    )


def browser_source() -> Source:
    return Source(
        id="aa-browser",
        fellowship="aa",
        name="Browser AA",
        url="https://browser.example.org/meetings",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
        config={"selectors": {"row": ".meeting"}},
        requires_browser=True,
    )


def test_pdf_normalize_requires_source_specific_parser() -> None:
    adapter = PdfAdapter(pdf_source())
    raw = RawMeeting(
        source_id="aa-pdf",
        source_record_id="pdf",
        source_url="https://pdf.example.org/meetings.pdf",
        payload={"text": "meeting text"},
        content_hash="hash",
    )

    with pytest.raises(AdapterPayloadError):
        adapter.normalize(raw)


def test_playwright_normalize_delegates_to_static_parser_and_requires_selectors() -> None:
    adapter = PlaywrightBrowserAdapter(browser_source())
    raw = RawMeeting(
        source_id="aa-browser",
        source_record_id="browser",
        source_url="https://browser.example.org/meetings",
        payload={},
        content_hash="hash",
    )

    with pytest.raises(AdapterPayloadError):
        adapter.normalize(raw)


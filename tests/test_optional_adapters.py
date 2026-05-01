import pytest

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.adapters.pdf import PdfAdapter
from app.adapters.playwright_browser import PlaywrightBrowserAdapter, perform_browser_actions
from app.config import Settings
from app.ingest import ingest_source
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


async def test_playwright_actions_drive_configured_interactions() -> None:
    page = FakePage()

    await perform_browser_actions(
        page,
        [
            {"type": "fill", "selector": "#postcode", "value": "Dublin"},
            {"type": "select_option", "selector": "#day", "label": "Monday"},
            {"type": "click", "selector": "button[type=submit]", "wait_for": ".meeting"},
            {"type": "wait_for_load_state", "state": "networkidle"},
        ],
    )

    assert page.calls == [
        ("fill", "#postcode", "Dublin"),
        ("select_option", "#day", {"label": "Monday"}),
        ("click", "button[type=submit]"),
        ("wait_for_selector", ".meeting"),
        ("wait_for_load_state", "networkidle"),
    ]


async def test_playwright_actions_reject_unknown_action() -> None:
    with pytest.raises(AdapterPayloadError, match="unsupported browser action type"):
        await perform_browser_actions(FakePage(), [{"type": "drag", "selector": "#item"}])


async def test_playwright_adapter_extracts_rendered_table_without_selectors(tmp_path) -> None:
    html = """
    <table>
      <tr><th>Meeting</th><th>Day</th><th>Time</th><th>Address</th></tr>
      <tr><td>Monday Main</td><td>Monday</td><td>7:30 pm</td><td>10 Main Street</td></tr>
    </table>
    """
    fixture = tmp_path / "meetings.html"
    fixture.write_text(html, encoding="utf-8")
    source = browser_source().model_copy(update={"config": {"timezone": "Europe/Dublin"}})

    result = await ingest_source(source, Settings(), fixture=fixture)

    assert len(result.raw_records) == 1
    assert result.raw_records[0].payload["extraction"]["method"] == "heuristic_table_row"
    assert result.candidates[0].name == "Monday Main"
    assert result.candidates[0].occurrences[0].timezone == "Europe/Dublin"


class FakePage:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def fill(self, selector: str, value: str) -> None:
        self.calls.append(("fill", selector, value))

    async def select_option(self, selector: str, value: object) -> None:
        self.calls.append(("select_option", selector, value))

    async def click(self, selector: str) -> None:
        self.calls.append(("click", selector))

    async def wait_for_selector(self, selector: str) -> None:
        self.calls.append(("wait_for_selector", selector))

    async def wait_for_load_state(self, state: str) -> None:
        self.calls.append(("wait_for_load_state", state))

    async def wait_for_timeout(self, milliseconds: int) -> None:
        self.calls.append(("wait_for_timeout", milliseconds))

    async def press(self, selector: str, key: str) -> None:
        self.calls.append(("press", selector, key))

    async def check(self, selector: str) -> None:
        self.calls.append(("check", selector))

    async def uncheck(self, selector: str) -> None:
        self.calls.append(("uncheck", selector))

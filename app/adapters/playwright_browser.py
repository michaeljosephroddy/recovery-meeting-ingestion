import hashlib

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.adapters.static_html import StaticHtmlAdapter
from app.normalize.canonical import CanonicalMeetingCandidate
from app.sources.registry import Source


class PlaywrightBrowserAdapter:
    def __init__(
        self,
        source: Source,
        timeout_ms: int = 15_000,
    ) -> None:
        self.source = source
        self.timeout_ms = timeout_ms

    async def fetch(self) -> list[RawMeeting]:
        try:
            from playwright.async_api import async_playwright  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AdapterPayloadError(
                "playwright optional dependency is required for browser automation"
            ) from exc

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page()
            page.set_default_timeout(self.timeout_ms)
            await page.goto(self.source.url, wait_until="networkidle")
            wait_for_selector = self.source.config.get("wait_for_selector")
            if wait_for_selector:
                await page.wait_for_selector(str(wait_for_selector))
            html = await page.content()
            await browser.close()

        return StaticHtmlAdapter(self.source).raw_records_from_html(html)

    def raw_records_from_html(self, html: str) -> list[RawMeeting]:
        return StaticHtmlAdapter(self.source).raw_records_from_html(html)

    def normalize(self, raw: RawMeeting) -> CanonicalMeetingCandidate:
        try:
            return StaticHtmlAdapter(self.source).normalize(raw)
        except Exception as exc:
            raise AdapterPayloadError("browser adapter output could not be normalized") from exc


def browser_payload_id(html: str) -> str:
    return hashlib.sha1(html.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]

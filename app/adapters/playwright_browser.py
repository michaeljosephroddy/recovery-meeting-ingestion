import hashlib
from typing import Any, Literal, cast

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.adapters.static_html import StaticHtmlAdapter
from app.normalize.canonical import CanonicalMeetingCandidate
from app.scraping.extract_meetings import extract_meetings_from_html
from app.scraping.interactions import (
    browser_config_from_source,
    configured_actions_from_source,
    perform_configured_actions,
)
from app.scraping.raw_records import raw_records_from_extracted
from app.sources.registry import Source

WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]


class PlaywrightBrowserAdapter:
    def __init__(
        self,
        source: Source,
        user_agent: str = "SoberSpaceRecoveryMeetingIngestion/0.1",
        timeout_ms: int = 15_000,
    ) -> None:
        self.source = source
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms

    async def fetch(self) -> list[RawMeeting]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise AdapterPayloadError(
                "playwright optional dependency is required for browser automation"
            ) from exc

        browser_config = browser_config_from_source(self.source)
        timeout_ms = _int_config(browser_config, "timeout_ms", self.timeout_ms)
        wait_until = _wait_until_config(browser_config)
        headless = _bool_config(browser_config, "headless", True)

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=headless)
            page = await browser.new_page(user_agent=self.user_agent)
            page.set_default_timeout(timeout_ms)
            await page.goto(self.source.url, wait_until=wait_until)
            await perform_configured_actions(page, configured_actions_from_source(self.source))
            wait_for_selector = browser_config.get("wait_for_selector")
            if wait_for_selector:
                await page.wait_for_selector(str(wait_for_selector))
            html = await page.content()
            await browser.close()

        return self.raw_records_from_html(html)

    def raw_records_from_html(self, html: str) -> list[RawMeeting]:
        extracted = extract_meetings_from_html(
            html,
            source_page_url=self.source.url,
            source_config=self.source.config,
        )
        return raw_records_from_extracted(self.source, extracted)

    def normalize(self, raw: RawMeeting) -> CanonicalMeetingCandidate:
        try:
            return StaticHtmlAdapter(self.source).normalize(raw)
        except Exception as exc:
            raise AdapterPayloadError("browser adapter output could not be normalized") from exc


def browser_payload_id(html: str) -> str:
    return hashlib.sha1(html.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


async def perform_browser_actions(page: Any, actions: object) -> None:
    await perform_configured_actions(page, actions)


def _int_config(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AdapterPayloadError(f"browser config {key} must be an integer") from exc


def _bool_config(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise AdapterPayloadError(f"browser config {key} must be a boolean")


def _wait_until_config(config: dict[str, Any]) -> WaitUntil:
    value = str(config.get("wait_until") or "networkidle")
    if value in {"commit", "domcontentloaded", "load", "networkidle"}:
        return cast(WaitUntil, value)
    raise AdapterPayloadError(
        "browser config wait_until must be commit, domcontentloaded, load, or networkidle"
    )


def _required_string(action: dict[str, Any], key: str, index: int) -> str:
    value = action.get(key)
    if value is None or str(value).strip() == "":
        raise AdapterPayloadError(f"browser action {index} is missing {key}")
    return str(value)


def _required_int(action: dict[str, Any], key: str, index: int) -> int:
    value = action.get(key)
    if value is None:
        raise AdapterPayloadError(f"browser action {index} is missing {key}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AdapterPayloadError(f"browser action {index} {key} must be an integer") from exc


def _select_option_value(action: dict[str, Any], index: int) -> object:
    if "options" in action:
        return action["options"]
    if "value" in action:
        return str(action["value"])
    if "label" in action:
        return {"label": str(action["label"])}
    if "index" in action:
        return {"index": _required_int(action, "index", index)}
    raise AdapterPayloadError(f"browser action {index} is missing value, label, index, or options")

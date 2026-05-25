import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from app.sources.registry import AdapterType, Source, SourceType

MEETING_GUIDE_PATHS = (
    "/meetings.json",
    "/wp-json/meeting-guide/v1/meetings",
)
BMLT_PATHS = (
    "/main_server/client_interface/json/?switcher=GetSearchResults",
    "/client_interface/json/?switcher=GetSearchResults",
)
JSON_URL_RE = re.compile(
    r"""["'](?P<url>[^"']*(?:meetings\.json|meeting-guide/v1/meetings|client_interface/json)[^"']*)["']""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClassificationResult:
    source: Source
    changed: bool
    reason: str


class SourceProbeClassifier:
    def __init__(
        self,
        *,
        user_agent: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.user_agent = user_agent
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    async def classify(self, source: Source) -> ClassificationResult:
        if source.url.startswith("tel:"):
            return self._updated(
                source,
                adapter_type=AdapterType.MANUAL_REVIEW,
                source_type=SourceType.PHONE,
                reason="phone-only source",
            )
        if source.url.lower().endswith(".pdf"):
            return self._updated(
                source,
                adapter_type=AdapterType.MANUAL_REVIEW,
                source_type=SourceType.PDF,
                reason="PDF source requires source-specific review before normalization",
            )

        async with httpx.AsyncClient(
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout_seconds,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            home_response = await client.get(source.url)
            home_response.raise_for_status()
            if self._looks_like_meeting_guide_payload(home_response):
                return self._updated(
                    source,
                    adapter_type=AdapterType.MEETING_GUIDE,
                    source_type=SourceType.MEETING_FEED,
                    requires_browser=False,
                    config_updates={"meeting_guide_feed_url": str(home_response.url)},
                    reason="source URL returned Meeting Guide JSON",
                )
            if self._looks_like_bmlt_payload(home_response):
                return self._updated(
                    source,
                    adapter_type=AdapterType.BMLT,
                    source_type=SourceType.MEETING_FEED,
                    requires_browser=False,
                    config_updates={"bmlt_search_endpoint": str(home_response.url)},
                    reason="source URL returned BMLT JSON",
                )

            html = home_response.text
            for url in self._candidate_meeting_guide_urls(str(home_response.url), html):
                if await self._probe_meeting_guide(client, url):
                    return self._updated(
                        source,
                        adapter_type=AdapterType.MEETING_GUIDE,
                        source_type=SourceType.MEETING_FEED,
                        requires_browser=False,
                        config_updates={"meeting_guide_feed_url": url},
                        reason="discovered Meeting Guide JSON feed",
                    )

            for url in self._candidate_bmlt_urls(str(home_response.url), html):
                endpoint = self._bmlt_search_endpoint(url)
                if await self._probe_bmlt(client, endpoint):
                    return self._updated(
                        source,
                        adapter_type=AdapterType.BMLT,
                        source_type=SourceType.MEETING_FEED,
                        requires_browser=False,
                        config_updates={"bmlt_search_endpoint": endpoint},
                        reason="discovered BMLT JSON endpoint",
                    )

            if self._has_meeting_form(html):
                return self._updated(
                    source,
                    adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
                    requires_browser=True,
                    reason="meeting search form found; browser crawler can interact with it",
                )
            if self._has_meeting_page(html):
                return self._updated(
                    source,
                    adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
                    requires_browser=True,
                    reason="meeting page found; browser crawler can extract rendered content",
                )

        return self._updated(source, reason="no supported meeting feed detected")

    def _candidate_meeting_guide_urls(self, base_url: str, html: str) -> list[str]:
        urls = [urljoin(base_url, path) for path in MEETING_GUIDE_PATHS]
        urls.extend(
            self._matching_urls(
                base_url,
                html,
                ("meetings.json", "meeting-guide/v1/meetings"),
            )
        )
        return _dedupe_urls(urls)

    def _candidate_bmlt_urls(self, base_url: str, html: str) -> list[str]:
        urls = [urljoin(base_url, path) for path in BMLT_PATHS]
        urls.extend(self._matching_urls(base_url, html, ("client_interface/json", "main_server")))
        return _dedupe_urls(urls)

    def _matching_urls(self, base_url: str, html: str, needles: tuple[str, ...]) -> list[str]:
        parser = HTMLParser(html)
        urls: list[str] = []
        for node in parser.css("a, script, link"):
            href = node.attributes.get("href") or node.attributes.get("src")
            if href and any(needle in href.lower() for needle in needles):
                urls.append(urljoin(base_url, href))
        for match in JSON_URL_RE.finditer(html):
            value = match.group("url")
            if any(needle in value.lower() for needle in needles):
                urls.append(urljoin(base_url, value))
        return urls

    async def _probe_meeting_guide(self, client: httpx.AsyncClient, url: str) -> bool:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except (httpx.HTTPError, httpx.TransportError):
            return False
        return self._looks_like_meeting_guide_payload(response)

    async def _probe_bmlt(self, client: httpx.AsyncClient, url: str) -> bool:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except (httpx.HTTPError, httpx.TransportError):
            return False
        return self._looks_like_bmlt_payload(response)

    def _looks_like_meeting_guide_payload(self, response: httpx.Response) -> bool:
        payload = _json_payload(response)
        if not _is_object_array(payload):
            return False
        sample = payload[0] if payload else {}
        return bool(
            {"name", "slug"}.intersection(sample)
            and {"day", "time", "address", "conference_url", "location"}.intersection(sample)
        )

    def _looks_like_bmlt_payload(self, response: httpx.Response) -> bool:
        payload = _json_payload(response)
        if not _is_object_array(payload):
            return False
        sample = payload[0] if payload else {}
        return bool(
            {"id_bigint", "weekday_tinyint", "start_time", "meeting_name"}.intersection(sample)
        )

    def _bmlt_search_endpoint(self, url: str) -> str:
        if "client_interface/json" in url:
            return url
        return url.rstrip("/") + "/client_interface/json/?switcher=GetSearchResults"

    def _has_meeting_form(self, html: str) -> bool:
        parser = HTMLParser(html)
        for form in parser.css("form"):
            text = " ".join(form.text(separator=" ", strip=True).lower().split())
            attrs = " ".join(str(value).lower() for value in form.attributes.values())
            field_attrs = " ".join(
                str(value).lower()
                for field in form.css("input, select, button")
                for value in field.attributes.values()
            )
            if "meeting" in text or "meeting" in attrs or "meeting" in field_attrs:
                return True
        return False

    def _has_meeting_page(self, html: str) -> bool:
        parser = HTMLParser(html)
        for link in parser.css("a"):
            href = link.attributes.get("href") or ""
            text = link.text(separator=" ", strip=True)
            value = f"{href} {text}".lower()
            if "meeting" in value or "find-a-meeting" in value:
                return True
        return False

    def _updated(
        self,
        source: Source,
        *,
        adapter_type: AdapterType | None = None,
        source_type: SourceType | None = None,
        requires_browser: bool | None = None,
        config_updates: dict[str, Any] | None = None,
        reason: str,
    ) -> ClassificationResult:
        config = dict(source.config)
        classification = dict(config.get("classification") or {})
        classification["reason"] = reason
        if adapter_type is not None:
            classification["adapter_type"] = adapter_type.value
        config["classification"] = classification
        if config_updates:
            config.update(config_updates)

        updated = source.model_copy(
            update={
                "adapter_type": adapter_type or source.adapter_type,
                "source_type": source_type or source.source_type,
                "requires_browser": (
                    source.requires_browser if requires_browser is None else requires_browser
                ),
                "config": config,
            }
        )
        return ClassificationResult(
            source=updated,
            changed=updated.model_dump() != source.model_dump(),
            reason=reason,
        )


def _json_payload(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "").lower()
    if "json" not in content_type and not response.text.lstrip().startswith(("[", "{")):
        return None
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError):
        return None


def _is_object_array(payload: object) -> bool:
    return (
        isinstance(payload, list)
        and bool(payload)
        and all(isinstance(item, dict) for item in payload)
    )


def _dedupe_urls(urls: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        normalized = url.rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(url)
    return deduped[:20]

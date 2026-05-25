import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.sources.html_discovery import discover_source_links
from app.sources.registry import AdapterType, SourceCandidate, SourceType, normalize_source_url

NA_WORLD_URL = "https://na.org/meetingsearch/find-na/"
NA_LOCATOR_ENDPOINT = "https://na.org/wp-content/plugins/meetings-finder/ajax.php"
NA_ORPHAN_ENDPOINT = "https://na.org/wp-content/plugins/meetings-finder/orphans.php"
NA_BOOTSTRAP_SEED = {
    "lat": "40.7128",
    "lng": "-74.0060",
    "within": "0",
    "country": "United States",
    "state": "NY",
}


class NaWorldServicesDiscovery:
    def __init__(
        self,
        settings: Settings,
        url: str = NA_WORLD_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.url = url
        self.transport = transport

    async def fetch_html(self) -> str:
        async with httpx.AsyncClient(
            headers=self._browser_headers(),
            timeout=20.0,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            response = await client.get(self.url)
            response.raise_for_status()
            return response.text

    async def discover(self, max_locations: int | None = None) -> list[SourceCandidate]:
        try:
            return await self._discover_with_httpx(max_locations=max_locations)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 403 or self.transport is not None:
                raise
            return await self._discover_with_browser(max_locations=max_locations)

    def parse_html(self, html: str) -> list[SourceCandidate]:
        if html.lstrip().startswith("{"):
            return parse_locator_payload(html, world_source=self.url)
        return discover_source_links(html, base_url=self.url, fellowship="na")

    async def _discover_with_httpx(
        self,
        max_locations: int | None = None,
    ) -> list[SourceCandidate]:
        async with httpx.AsyncClient(
            headers=self._browser_headers(),
            timeout=30.0,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            landing = await client.get(self.url)
            landing.raise_for_status()

            async def post_locator(data: dict[str, str]) -> dict[str, Any]:
                return await self._post_locator(client, data)

            return await self._discover_from_locator(
                post_locator,
                max_locations=max_locations,
            )

    async def _discover_with_browser(
        self,
        max_locations: int | None = None,
    ) -> list[SourceCandidate]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "NA locator blocked direct HTTP discovery and Playwright is not installed"
            ) from exc

        endpoint_path = urlparse(NA_LOCATOR_ENDPOINT).path
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                response = await page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
                if response is not None and response.status >= 400:
                    raise RuntimeError(
                        f"NA locator page returned HTTP {response.status} in browser fallback"
                    )

                async def post_locator(data: dict[str, str]) -> dict[str, Any]:
                    result = await page.evaluate(
                        """
                        async ({ endpointPath, data }) => {
                          const response = await fetch(endpointPath, {
                            method: "POST",
                            headers: {
                              "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                              "X-Requested-With": "XMLHttpRequest",
                              "Accept": "application/json, text/javascript, */*; q=0.01"
                            },
                            body: new URLSearchParams(data).toString(),
                            credentials: "same-origin"
                          });
                          return {
                            status: response.status,
                            text: await response.text()
                          };
                        }
                        """,
                        {"endpointPath": endpoint_path, "data": data},
                    )
                    if not isinstance(result, dict):
                        raise ValueError("NA locator browser response was not an object")
                    status = int(result.get("status") or 0)
                    text = str(result.get("text") or "")
                    if status >= 400:
                        raise RuntimeError(
                            f"NA locator browser request returned HTTP {status}: {text[:120]}"
                        )
                    payload = json.loads(text)
                    if not isinstance(payload, dict):
                        raise ValueError("NA locator response was not a JSON object")
                    if payload.get("status") != "success":
                        raise ValueError(f"NA locator returned status={payload.get('status')!r}")
                    return payload

                return await self._discover_from_locator(
                    post_locator,
                    max_locations=max_locations,
                )
            finally:
                await browser.close()

    async def _discover_from_locator(
        self,
        post_locator: Callable[[dict[str, str]], Awaitable[dict[str, Any]]],
        *,
        max_locations: int | None = None,
    ) -> list[SourceCandidate]:
        index_payload = await post_locator({"action": "search", **NA_BOOTSTRAP_SEED})
        locations = parse_location_index(index_payload)
        if max_locations is not None:
            locations = locations[:max_locations]

        candidates = parse_locator_payload(index_payload, world_source=self.url)
        for location in locations:
            payload = await post_locator({"action": "listings", **location})
            candidates.extend(parse_locator_payload(payload, world_source=self.url))
            if self.settings.default_rate_limit_seconds > 0:
                await asyncio.sleep(self.settings.default_rate_limit_seconds)

        return _unique_candidates(candidates)

    async def _post_locator(self, client, data: dict[str, str]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        response = await client.post(
            NA_LOCATOR_ENDPOINT,
            data=data,
            headers={
                "Referer": self.url,
                "Origin": "https://na.org",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("NA locator response was not a JSON object")
        if payload.get("status") != "success":
            raise ValueError(f"NA locator returned status={payload.get('status')!r}")
        return payload

    def _browser_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
                f"{self.settings.user_agent}"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }


def parse_location_index(payload: str | Mapping[str, Any]) -> list[dict[str, str]]:
    data = _payload_dict(payload)
    locations: list[dict[str, str]] = []

    for item in data.get("ll_us", []):
        if isinstance(item, Mapping) and item.get("state"):
            locations.append({"country": "United States", "state": str(item["state"])})

    for item in data.get("ll_ca", []):
        if isinstance(item, Mapping) and item.get("state"):
            locations.append({"country": "Canada", "state": str(item["state"])})

    for item in data.get("ll_intl", []):
        if isinstance(item, Mapping) and item.get("country"):
            locations.append({"country": str(item["country"]), "state": ""})

    return locations


def parse_locator_payload(
    payload: str | Mapping[str, Any],
    *,
    world_source: str = NA_WORLD_URL,
) -> list[SourceCandidate]:
    data = _payload_dict(payload)
    candidates: list[SourceCandidate] = []
    for item in data.get("data", []):
        if not isinstance(item, Mapping):
            continue
        website = _normalize_website(str(item.get("website") or "").strip())
        description = str(item.get("description") or website or "NA local service body").strip()
        country = _blank_to_none(item.get("country"))
        region = _blank_to_none(item.get("state"))
        metadata = {
            "world_source": world_source,
            "na_type": _blank_to_none(item.get("type")),
            "na_group_code": _blank_to_none(item.get("groupcode")),
            "city": _blank_to_none(item.get("city")),
            "postal_code": _blank_to_none(item.get("postal_code")),
            "phone": _blank_to_none(item.get("phone")),
            "phone2": _blank_to_none(item.get("phone2")),
            "whatsapp": _blank_to_none(item.get("whatsapp")),
        }
        metadata = {key: value for key, value in metadata.items() if value is not None}

        if website:
            candidates.append(
                SourceCandidate(
                    fellowship="na",
                    url=website,
                    label=description,
                    country=country,
                    region=region,
                    source_type=SourceType.LOCAL_SERVICE_BODY,
                    metadata=metadata,
                )
            )
            continue

        phonewebid = _blank_to_none(item.get("phonewebid"))
        phone = _blank_to_none(item.get("phone")) or _blank_to_none(item.get("phone2"))
        if phonewebid is not None:
            candidates.append(
                SourceCandidate(
                    fellowship="na",
                    url=f"{NA_ORPHAN_ENDPOINT}?id={phonewebid}",
                    label=f"{description} phoneline",
                    country=country,
                    region=region,
                    source_type=SourceType.PHONE,
                    adapter_type=AdapterType.MANUAL_REVIEW,
                    metadata=metadata,
                )
            )
        elif phone is not None:
            candidates.append(
                SourceCandidate(
                    fellowship="na",
                    url=f"tel:{_sanitize_phone_uri(phone)}",
                    label=f"{description} phoneline",
                    country=country,
                    region=region,
                    source_type=SourceType.PHONE,
                    adapter_type=AdapterType.MANUAL_REVIEW,
                    metadata=metadata,
                )
            )

    return _unique_candidates(candidates)


def _payload_dict(payload: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(payload, str):
        parsed = json.loads(payload)
        if not isinstance(parsed, Mapping):
            raise ValueError("NA locator payload was not a JSON object")
        return parsed
    return payload


def _normalize_website(value: str) -> str | None:
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        return f"http://{value}"
    return value


def _blank_to_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _sanitize_phone_uri(phone: str) -> str:
    return re.sub(r"[^0-9+]", "", phone)


def _unique_candidates(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    unique: list[SourceCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate.fellowship, normalize_source_url(str(candidate.url)))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique

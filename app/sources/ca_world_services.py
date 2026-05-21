import asyncio
from collections import deque
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.sources.registry import (
    AdapterType,
    SourceCandidate,
    SourceType,
    absolute_url,
    normalize_source_url,
)

CA_WORLD_URL = "https://ca.org/meetings/"
CA_WORLD_HOSTS = {"ca.org", "www.ca.org"}
CA_ONLINE_HOSTS = {"ca-online.org", "www.ca-online.org"}
CA_NOISE_HOSTS = {
    "apps.apple.com",
    "calendar.google.com",
    "docs.google.com",
    "drive.google.com",
    "goo.gl",
    "maps.app.goo.gl",
    "meet.google.com",
    "play.google.com",
    "museum.ca.org",
    "superbthemes.com",
    "tinyurl.com",
    "wordpress.org",
    "zoom.us",
}
CA_NOISE_PATH_PARTS = {
    "newsgram",
    "gdpr-cookie-compliance",
}
CA_ONLINE_LOCAL_SOURCE_PATHS = {"", "/"}


class CaWorldServicesDiscovery:
    def __init__(
        self,
        settings: Settings,
        url: str = CA_WORLD_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.url = url
        self.transport = transport

    async def fetch_html(self) -> str:
        async with httpx.AsyncClient(
            headers={"User-Agent": self.settings.user_agent},
            timeout=20.0,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            response = await client.get(self.url)
            response.raise_for_status()
            return response.text

    async def discover(self, max_locations: int | None = None) -> list[SourceCandidate]:
        async with httpx.AsyncClient(
            headers={"User-Agent": self.settings.user_agent},
            timeout=20.0,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            response = await client.get(self.url)
            response.raise_for_status()
            candidates = self.parse_html_for_url(response.text, self.url)

            listing_queue: deque[SourceCandidate] = deque(
                candidate
                for candidate in candidates
                if candidate.source_type == SourceType.WORLD_SERVICE_LISTING
            )
            fetched_listing_urls: set[str] = set()
            fetched_count = 0
            while listing_queue:
                if max_locations is not None and fetched_count >= max_locations:
                    break
                page = listing_queue.popleft()
                normalized_page_url = normalize_source_url(str(page.url))
                if normalized_page_url in fetched_listing_urls:
                    continue
                fetched_listing_urls.add(normalized_page_url)
                fetched_count += 1
                page_response = await client.get(str(page.url))
                page_response.raise_for_status()
                final_url = str(page_response.url)
                if _is_external_local_source(urlparse(final_url)):
                    candidates.append(
                        SourceCandidate(
                            fellowship="ca",
                            url=final_url,
                            label=page.label,
                            country=page.country,
                            region=page.region,
                            source_type=SourceType.LOCAL_SERVICE_BODY,
                            metadata={"world_source": str(page.url)},
                        )
                    )
                    if self.settings.default_rate_limit_seconds > 0:
                        await asyncio.sleep(self.settings.default_rate_limit_seconds)
                    continue
                discovered = self.parse_html_for_url(page_response.text, final_url)
                candidates.extend(discovered)
                for candidate in discovered:
                    if candidate.source_type != SourceType.WORLD_SERVICE_LISTING:
                        continue
                    normalized_candidate_url = normalize_source_url(str(candidate.url))
                    if normalized_candidate_url not in fetched_listing_urls:
                        listing_queue.append(candidate)
                if self.settings.default_rate_limit_seconds > 0:
                    await asyncio.sleep(self.settings.default_rate_limit_seconds)

        return _unique_candidates(candidates)

    def parse_html(self, html: str) -> list[SourceCandidate]:
        return self.parse_html_for_url(html, self.url)

    def parse_html_for_url(self, html: str, base_url: str) -> list[SourceCandidate]:
        from selectolax.parser import HTMLParser

        parser = HTMLParser(html)
        candidates: list[SourceCandidate] = []
        page_country = _country_from_meetings_path(base_url)
        for link in parser.css("a"):
            href = link.attributes.get("href")
            label = " ".join(link.text(separator=" ", strip=True).split())
            if not href or not label or href.startswith(("#", "mailto:", "tel:")):
                continue

            url = absolute_url(base_url, href)
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                continue

            if _is_ca_world_listing(parsed):
                if normalize_source_url(url) == normalize_source_url(CA_WORLD_URL):
                    continue
                candidates.append(
                    SourceCandidate(
                        fellowship="ca",
                        url=url,
                        label=label,
                        country=_country_from_meetings_path(url),
                        region=_region_from_meetings_path(url),
                        source_type=SourceType.WORLD_SERVICE_LISTING,
                        metadata={"world_source": CA_WORLD_URL},
                    )
                )
                continue

            if _is_external_local_source(parsed):
                source_type = (
                    SourceType.PDF
                    if parsed.path.lower().endswith(".pdf")
                    else SourceType.LOCAL_SERVICE_BODY
                )
                adapter_type = (
                    AdapterType.PDF if source_type == SourceType.PDF else AdapterType.UNKNOWN
                )
                candidates.append(
                    SourceCandidate(
                        fellowship="ca",
                        url=url,
                        label=label,
                        country=page_country,
                        region=_region_from_meetings_path(base_url),
                        source_type=source_type,
                        adapter_type=adapter_type,
                        metadata={"world_source": base_url},
                    )
                )

        return _unique_candidates(candidates)


def _is_ca_world_listing(parsed_url) -> bool:  # type: ignore[no-untyped-def]
    path = parsed_url.path.rstrip("/") + "/"
    return (
        parsed_url.netloc.lower() in CA_WORLD_HOSTS
        and path.startswith("/meetings/")
        and path != "/meetings/"
    )


def _is_external_local_source(parsed_url) -> bool:  # type: ignore[no-untyped-def]
    host = parsed_url.netloc.lower()
    base_host = host.removeprefix("www.")
    path = parsed_url.path.lower()
    if host in CA_WORLD_HOSTS or host in CA_NOISE_HOSTS or base_host in CA_NOISE_HOSTS:
        return False
    if host.endswith(".zoom.us"):
        return False
    if host in CA_ONLINE_HOSTS:
        return path.rstrip("/") in CA_ONLINE_LOCAL_SOURCE_PATHS
    return not any(part in path for part in CA_NOISE_PATH_PARTS)


def is_valid_ca_local_source_url(url: str) -> bool:
    parsed = urlparse(url)
    return _is_external_local_source(parsed)


def _country_from_meetings_path(url: str) -> str | None:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if len(path_parts) < 2 or path_parts[0] != "meetings":
        return None
    return path_parts[1].replace("-", " ").title()


def _region_from_meetings_path(url: str) -> str | None:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if len(path_parts) < 3 or path_parts[0] != "meetings":
        return None
    return path_parts[-1].replace("-", " ").title()


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

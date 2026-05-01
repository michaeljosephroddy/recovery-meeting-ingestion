import asyncio
import re
from collections.abc import Iterable
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

AA_WORLD_URL = "https://www.aa.org/find-aa/world"
AA_WORLD_HOSTS = {"aa.org", "www.aa.org"}
AA_DISCOVERY_QUERIES = (
    ("state", "CA"),
    ("state", "ON"),
    ("cc", "IE"),
)
AA_NOISE_HOSTS = {
    "contribution.aa.org",
    "onlineliterature.aa.org",
    "recruiting.paylocity.com",
    "www.aagrapevine.org",
}


class AaWorldServicesDiscovery:
    def __init__(
        self,
        settings: Settings,
        url: str = AA_WORLD_URL,
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
        candidates: list[SourceCandidate] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": self.settings.user_agent},
            timeout=30.0,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            index_response = await client.get(self.url)
            index_response.raise_for_status()
            candidates.extend(self.parse_html_for_url(index_response.text, str(index_response.url)))
            queries = aa_filter_queries_from_html(index_response.text)
            if not queries:
                queries = list(AA_DISCOVERY_QUERIES)
            if max_locations is not None:
                queries = queries[:max_locations]
            for key, value in queries:
                response = await client.get(self.url, params={key: value})
                response.raise_for_status()
                candidates.extend(self.parse_html_for_url(response.text, str(response.url)))
                if self.settings.default_rate_limit_seconds > 0:
                    await asyncio.sleep(self.settings.default_rate_limit_seconds)

        return _unique_candidates(candidates)

    def parse_html(self, html: str) -> list[SourceCandidate]:
        return self.parse_html_for_url(html, self.url)

    def parse_html_for_url(self, html: str, base_url: str) -> list[SourceCandidate]:
        from selectolax.parser import HTMLParser

        parser = HTMLParser(html)
        candidates: list[SourceCandidate] = []
        for item in parser.css(".view-locations-listing .area-loc-item"):
            heading = item.css_first("h3")
            if heading is None:
                continue

            label = " ".join(heading.text(separator=" ", strip=True).split())
            if not label:
                continue

            address = item.css_first("address")
            address_text = (
                " ".join(address.text(separator=" ", strip=True).split()) if address else ""
            )
            country = _country_from_item(item, address_text)
            region = _region_from_item(item, address_text)
            phone = _phone_from_item(item)
            metadata = {
                "world_source": AA_WORLD_URL,
                "source_listing": base_url,
                "address_text": address_text or None,
                "phone": phone,
            }
            metadata = {key: value for key, value in metadata.items() if value is not None}

            link = _first_source_link(item, base_url)
            if link is not None:
                candidates.append(
                    SourceCandidate(
                        fellowship="aa",
                        url=link,
                        label=label,
                        country=country,
                        region=region,
                        source_type=SourceType.LOCAL_SERVICE_BODY,
                        metadata=metadata,
                    )
                )
                continue

            if phone is not None:
                candidates.append(
                    SourceCandidate(
                        fellowship="aa",
                        url=f"tel:{_sanitize_phone_uri(phone)}",
                        label=f"{label} phoneline",
                        country=country,
                        region=region,
                        source_type=SourceType.PHONE,
                        adapter_type=AdapterType.MANUAL_REVIEW,
                        metadata=metadata,
                    )
                )

        return _unique_candidates(candidates)


def aa_filter_queries_from_html(html: str) -> list[tuple[str, str]]:
    from selectolax.parser import HTMLParser

    parser = HTMLParser(html)
    queries: list[tuple[str, str]] = []
    queries.extend(_option_queries(parser.css("select[name='state']"), key="state"))
    queries.extend(_option_queries(parser.css("select[name='cc']"), key="cc"))
    return _unique_queries(queries)


def _option_queries(selects: Iterable[object], *, key: str) -> list[tuple[str, str]]:
    queries: list[tuple[str, str]] = []
    for select in selects:
        for option in select.css("option"):  # type: ignore[attr-defined]
            value = str(option.attributes.get("value") or "").strip()
            if not value or value == "All":
                continue
            queries.append((key, value))
    return queries


def _unique_queries(queries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    unique: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for query in queries:
        if query in seen:
            continue
        seen.add(query)
        unique.append(query)
    return unique


def _first_source_link(item, base_url: str) -> str | None:  # type: ignore[no-untyped-def]
    for link in item.css("a"):
        href = link.attributes.get("href")
        if not href:
            continue
        url = absolute_url(base_url, href)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.netloc.lower() in AA_WORLD_HOSTS or parsed.netloc.lower() in AA_NOISE_HOSTS:
            continue
        if url.rstrip("/") in {"http:/", "https:"}:
            continue
        return url
    return None


def _country_from_item(item, address_text: str) -> str | None:  # type: ignore[no-untyped-def]
    country = item.css_first(".country")
    if country is not None:
        text = " ".join(country.text(separator=" ", strip=True).split())
        if text:
            return text
    if "Canada" in address_text:
        return "Canada"
    if "United States" in address_text or _region_from_item(item, address_text) in US_REGION_NAMES:
        return "United States"
    return None


def _region_from_item(item, address_text: str) -> str | None:  # type: ignore[no-untyped-def]
    region = item.css_first(".administrative-area")
    if region is not None:
        text = " ".join(region.text(separator=" ", strip=True).split())
        if text:
            return text

    for known_region in sorted(US_REGION_NAMES | CANADA_REGION_NAMES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(known_region)}\b", address_text):
            return known_region
    return None


def _phone_from_item(item) -> str | None:  # type: ignore[no-untyped-def]
    text = " ".join(item.text(separator=" ", strip=True).split())
    match = re.search(r"(?:Phone|Helpline|Answering Service):\s*([^A-Za-z]+)", text)
    if not match:
        return None
    phone = match.group(1).strip()
    return phone or None


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


US_REGION_NAMES = {
    "Alabama",
    "Alaska",
    "American Samoa",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "District of Columbia",
    "Florida",
    "Georgia",
    "Guam",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Marshall Islands",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Micronesia",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Northern Mariana Islands",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Palau",
    "Pennsylvania",
    "Puerto Rico",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virgin Islands",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
}

CANADA_REGION_NAMES = {
    "Alberta",
    "British Columbia",
    "Manitoba",
    "New Brunswick",
    "Newfoundland and Labrador",
    "Northwest Territories",
    "Nova Scotia",
    "Nunavut",
    "Ontario",
    "Prince Edward Island",
    "Quebec",
    "Saskatchewan",
    "Yukon",
}

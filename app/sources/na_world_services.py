import asyncio
import json
import re
from collections.abc import Mapping
from typing import Any

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
    def __init__(self, settings: Settings, url: str = NA_WORLD_URL) -> None:
        self.settings = settings
        self.url = url

    async def fetch_html(self) -> str:
        import httpx

        async with httpx.AsyncClient(
            headers={"User-Agent": self.settings.user_agent},
            timeout=20.0,
            follow_redirects=True,
        ) as client:
            response = await client.get(self.url)
            response.raise_for_status()
            return response.text

    async def discover(self, max_locations: int | None = None) -> list[SourceCandidate]:
        import httpx

        headers = {
            "User-Agent": self.settings.user_agent,
            "Referer": self.url,
            "Origin": "https://na.org",
        }
        async with httpx.AsyncClient(
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            index_payload = await self._post_locator(
                client,
                {"action": "search", **NA_BOOTSTRAP_SEED},
            )
            locations = parse_location_index(index_payload)
            if max_locations is not None:
                locations = locations[:max_locations]

            candidates = parse_locator_payload(index_payload, world_source=self.url)
            for location in locations:
                payload = await self._post_locator(client, {"action": "listings", **location})
                candidates.extend(parse_locator_payload(payload, world_source=self.url))
                if self.settings.default_rate_limit_seconds > 0:
                    await asyncio.sleep(self.settings.default_rate_limit_seconds)

        return _unique_candidates(candidates)

    def parse_html(self, html: str) -> list[SourceCandidate]:
        if html.lstrip().startswith("{"):
            return parse_locator_payload(html, world_source=self.url)
        return discover_source_links(html, base_url=self.url, fellowship="na")

    async def _post_locator(self, client, data: dict[str, str]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        response = await client.post(NA_LOCATOR_ENDPOINT, data=data)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("NA locator response was not a JSON object")
        if payload.get("status") != "success":
            raise ValueError(f"NA locator returned status={payload.get('status')!r}")
        return payload


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

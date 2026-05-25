import hashlib
import json
import re
from typing import Any

import httpx
from pydantic import HttpUrl, TypeAdapter, ValidationError

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.adapters.http import fetch_json_array
from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence
from app.normalize.schedule import normalize_day, parse_time
from app.sources.registry import Source, timezone_for_country_region

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


class BmltAdapter:
    def __init__(
        self,
        source: Source,
        user_agent: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.source = source
        self.user_agent = user_agent
        self.transport = transport

    async def fetch(self) -> list[RawMeeting]:
        endpoint = self.search_endpoint()
        payload = await fetch_json_array(
            endpoint,
            user_agent=self.user_agent,
            transport=self.transport,
        )
        return self.raw_records_from_payload(payload)

    def search_endpoint(self) -> str:
        configured = self.source.config.get("bmlt_search_endpoint")
        if configured:
            return str(configured)
        return self.source.url.rstrip("/") + "/client_interface/json/?switcher=GetSearchResults"

    def raw_records_from_payload(self, payload: list[dict[str, Any]]) -> list[RawMeeting]:
        records: list[RawMeeting] = []
        for item in payload:
            source_record_id = str(item.get("id_bigint") or item.get("id") or "")
            if not source_record_id:
                raise AdapterPayloadError("BMLT record is missing id_bigint or id")
            encoded = json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
            records.append(
                RawMeeting(
                    source_id=self.source.id,
                    source_record_id=source_record_id,
                    source_url=self.source.url,
                    payload=item,
                    content_hash=hashlib.sha256(encoded).hexdigest(),
                )
            )
        return records

    def normalize(self, raw: RawMeeting) -> CanonicalMeetingCandidate:
        item = raw.payload
        day = normalize_day(item.get("weekday_tinyint"))
        start = parse_time(item.get("start_time"))
        occurrences = []
        if day is not None and start is not None:
            occurrences.append(
                MeetingOccurrence(
                    day_of_week=day,
                    start_time_local=start,
                    timezone=str(
                        _non_utc_timezone(item.get("time_zone"))
                        or _non_utc_timezone(item.get("timezone"))
                        or self.source.config.get("timezone")
                        or _timezone_from_bmlt_location(item, self.source)
                        or "UTC"
                    ),
                )
            )
        raw_online_url = _text_or_none(item.get("virtual_meeting_link") or item.get("url"))
        online_url = _http_url_or_none(raw_online_url)
        phone_join_info = _text_or_none(
            item.get("phone_meeting_number") or item.get("virtual_meeting_additional_info")
        )
        if raw_online_url and online_url is None:
            phone_join_info = phone_join_info or raw_online_url
        has_online = bool(online_url or phone_join_info)
        has_address = bool(item.get("formatted_address") or item.get("location_text"))
        meeting_type = (
            "hybrid" if has_online and has_address else "online" if has_online else "in_person"
        )
        latitude = _float_or_none(item.get("latitude"))
        longitude = _float_or_none(item.get("longitude"))
        return CanonicalMeetingCandidate(
            fellowship=self.source.fellowship,
            source_id=raw.source_id,
            source_record_id=raw.source_record_id,
            source_url=raw.source_url,
            name=str(item.get("meeting_name") or item.get("name") or "NA/CA Meeting"),
            meeting_type=meeting_type,  # type: ignore[arg-type]
            venue_name=item.get("location_text"),
            address_line1=item.get("formatted_address") or item.get("street"),
            city=item.get("location_municipality"),
            region=item.get("location_province"),
            postal_code=item.get("location_postal_code_1"),
            country=item.get("location_nation") or self.source.country,
            latitude=latitude,
            longitude=longitude,
            online_url=online_url,
            phone_join_info=phone_join_info,
            formats=_split_formats(item.get("formats")),
            occurrences=occurrences,
        )


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)  # type: ignore[arg-type]


def _text_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _http_url_or_none(value: str | None) -> HttpUrl | None:
    if not value:
        return None
    try:
        return _HTTP_URL_ADAPTER.validate_python(value)
    except ValidationError:
        return None


def _split_formats(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _timezone_from_bmlt_location(item: dict[str, Any], source: Source) -> str | None:
    country = str(item.get("location_nation") or source.country or "")
    region = str(item.get("location_province") or source.region or "")
    if timezone := timezone_for_country_region(country, region):
        return timezone
    if country.casefold() in {"australia", "au"} or source.country == "Australia":
        return _australia_timezone_from_bmlt_location(item)
    return None


def _non_utc_timezone(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text.upper() == "UTC":
        return None
    return text


def _australia_timezone_from_bmlt_location(item: dict[str, Any]) -> str | None:
    postal_code = str(item.get("location_postal_code_1") or "")
    if match := re.search(r"\b(\d{4})\b", postal_code):
        prefix = match.group(1)[0]
        if prefix in {"1", "2"}:
            return "Australia/Sydney"
        if prefix in {"3", "8"}:
            return "Australia/Melbourne"
        if prefix == "4":
            return "Australia/Brisbane"
        if prefix == "5":
            return "Australia/Adelaide"
        if prefix == "6":
            return "Australia/Perth"
        if prefix == "7":
            return "Australia/Hobart"
        if match.group(1).startswith(("08", "09")):
            return "Australia/Darwin"

    longitude = _float_or_none(item.get("longitude"))
    latitude = _float_or_none(item.get("latitude"))
    if longitude is None or latitude is None:
        return None
    if not (112 <= longitude <= 154 and -44 <= latitude <= -10):
        return None
    if longitude < 129:
        return "Australia/Perth"
    if longitude < 138:
        return "Australia/Darwin" if latitude > -26 else "Australia/Adelaide"
    if longitude < 141:
        return "Australia/Adelaide"
    if latitude > -29:
        return "Australia/Brisbane"
    return "Australia/Sydney"

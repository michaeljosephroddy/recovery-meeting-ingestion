import hashlib
import json
from typing import Any

import httpx

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.adapters.http import fetch_json_array
from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence
from app.normalize.schedule import normalize_day, parse_time
from app.sources.registry import Source


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
                        item.get("time_zone")
                        or item.get("timezone")
                        or self.source.config.get("timezone")
                        or "UTC"
                    ),
                )
            )
        online_url = item.get("virtual_meeting_link") or item.get("url") or None
        has_online = bool(online_url)
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
            formats=_split_formats(item.get("formats")),
            occurrences=occurrences,
        )


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)  # type: ignore[arg-type]


def _split_formats(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [part.strip() for part in str(value).split(",") if part.strip()]

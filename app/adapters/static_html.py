import hashlib
import json
from typing import Any

import httpx

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.adapters.html_config import configured_selectors, extract_records_from_html
from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence
from app.normalize.schedule import normalize_days, parse_time
from app.sources.registry import Source


class StaticHtmlAdapter:
    def __init__(
        self,
        source: Source,
        user_agent: str = "SoberSpaceRecoveryMeetingIngestion/0.1",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.source = source
        self.user_agent = user_agent
        self.transport = transport

    async def fetch(self) -> list[RawMeeting]:
        async with httpx.AsyncClient(
            headers={"User-Agent": self.user_agent},
            timeout=20.0,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            response = await client.get(self.source.url)
            response.raise_for_status()
        return self.raw_records_from_html(response.text)

    def raw_records_from_html(self, html: str) -> list[RawMeeting]:
        selectors = configured_selectors(self.source.config)
        payloads = extract_records_from_html(html, selectors)
        records: list[RawMeeting] = []
        for payload in payloads:
            source_record_id = _source_record_id(payload)
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            records.append(
                RawMeeting(
                    source_id=self.source.id,
                    source_record_id=source_record_id,
                    source_url=self.source.url,
                    payload=payload,
                    content_hash=hashlib.sha256(encoded).hexdigest(),
                )
            )
        return records

    def normalize(self, raw: RawMeeting) -> CanonicalMeetingCandidate:
        payload = raw.payload
        days = normalize_days(_string(payload.get("day")))
        start = parse_time(_string(payload.get("time")))
        timezone = _string(payload.get("timezone")) or self.source.config.get("timezone") or "UTC"
        occurrences: list[MeetingOccurrence] = []
        if days and start is not None:
            occurrences.extend(
                MeetingOccurrence(
                    day_of_week=day,
                    start_time_local=start,
                    timezone=str(timezone),
                )
                for day in days
            )
        online_url = _string(payload.get("online_url"))
        phone = _string(payload.get("phone_join_info"))
        has_address = bool(
            payload.get("address_line1") or payload.get("city") or payload.get("venue_name")
        )
        has_online = bool(online_url or phone)
        attendance_option = str(payload.get("attendance_option") or "").lower().replace("_", " ")
        if "hybrid" in attendance_option:
            meeting_type = "hybrid"
        elif "online" in attendance_option:
            meeting_type = "hybrid" if has_address else "online"
        elif "in person" in attendance_option or "in-person" in attendance_option:
            meeting_type = "hybrid" if has_online else "in_person"
        else:
            meeting_type = (
                "hybrid" if has_address and has_online else "online" if has_online else "in_person"
            )
        return CanonicalMeetingCandidate(
            fellowship=self.source.fellowship,
            source_id=raw.source_id,
            source_record_id=raw.source_record_id,
            source_url=raw.source_url,
            name=_string(payload.get("name")) or "Recovery Meeting",
            meeting_type=meeting_type,  # type: ignore[arg-type]
            venue_name=_string(payload.get("venue_name")),
            address_line1=_string(payload.get("address_line1") or payload.get("address")),
            city=_string(payload.get("city")) or self.source.config.get("city"),
            region=_string(payload.get("region")) or self.source.region,
            country=_string(payload.get("country")) or self.source.country,
            online_url=online_url,  # type: ignore[arg-type]
            phone_join_info=phone,
            formats=_formats(payload.get("formats")),
            occurrences=occurrences,
        )


def _source_record_id(payload: dict[str, Any]) -> str:
    explicit = _string(payload.get("source_record_id") or payload.get("id"))
    if explicit:
        return explicit
    basis = "|".join(
        _string(payload.get(field)) or ""
        for field in ("name", "day", "time", "address_line1", "city", "online_url")
    )
    if not basis.strip("|"):
        raise AdapterPayloadError("HTML row is missing enough fields for a source record id")
    return hashlib.sha1(basis.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def _string(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _formats(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]

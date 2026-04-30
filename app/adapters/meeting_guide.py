import hashlib
import json
from typing import Any

import httpx

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.adapters.http import fetch_json_array
from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence
from app.normalize.schedule import normalize_day, parse_time
from app.sources.registry import Source


class MeetingGuideAdapter:
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
        payload = await fetch_json_array(
            self.feed_url(),
            user_agent=self.user_agent,
            transport=self.transport,
        )
        return self.raw_records_from_payload(payload)

    def feed_url(self) -> str:
        configured = self.source.config.get("meeting_guide_feed_url")
        if configured:
            return str(configured)
        return self.source.url

    def raw_records_from_payload(self, payload: list[dict[str, Any]]) -> list[RawMeeting]:
        records: list[RawMeeting] = []
        for item in payload:
            source_record_id = str(item.get("slug") or item.get("id") or "")
            if not source_record_id:
                raise AdapterPayloadError("Meeting Guide record is missing slug or id")
            encoded = json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
            records.append(
                RawMeeting(
                    source_id=self.source.id,
                    source_record_id=source_record_id,
                    source_url=self.feed_url(),
                    payload=item,
                    content_hash=hashlib.sha256(encoded).hexdigest(),
                )
            )
        return records

    def normalize(self, raw: RawMeeting) -> CanonicalMeetingCandidate:
        item = raw.payload
        day = normalize_day(item.get("day"))
        start = parse_time(item.get("time"))
        end = parse_time(item.get("end_time"))
        occurrences = []
        if day is not None and start is not None:
            occurrences.append(
                MeetingOccurrence(
                    day_of_week=day,
                    start_time_local=start,
                    end_time_local=end,
                    timezone=str(item.get("timezone") or "UTC"),
                )
            )

        has_online = bool(item.get("conference_url") or item.get("conference_phone"))
        has_address = bool(item.get("address") or item.get("city") or item.get("location"))
        meeting_type = "unknown"
        if has_online and has_address:
            meeting_type = "hybrid"
        elif has_online:
            meeting_type = "online"
        elif has_address:
            meeting_type = "in_person"

        return CanonicalMeetingCandidate(
            fellowship=self.source.fellowship,
            source_id=raw.source_id,
            source_record_id=raw.source_record_id,
            source_url=raw.source_url,
            name=str(item.get("name") or item.get("group") or "A.A. Meeting"),
            meeting_type=meeting_type,  # type: ignore[arg-type]
            venue_name=item.get("location"),
            address_line1=item.get("address"),
            city=item.get("city"),
            region=item.get("state"),
            postal_code=item.get("postal_code"),
            country=item.get("country") or self.source.country,
            online_url=item.get("conference_url") or None,
            phone_join_info=item.get("conference_phone") or None,
            formats=list(item.get("types") or []),
            occurrences=occurrences,
        )

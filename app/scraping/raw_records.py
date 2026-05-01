import hashlib
import json
from typing import Any

from app.adapters.base import RawMeeting
from app.scraping.models import ExtractedMeeting
from app.sources.registry import Source


def raw_records_from_extracted(
    source: Source,
    extracted: list[ExtractedMeeting],
) -> list[RawMeeting]:
    records: list[RawMeeting] = []
    for meeting in extracted:
        payload = meeting.payload_with_metadata()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        records.append(
            RawMeeting(
                source_id=source.id,
                source_record_id=_source_record_id(payload),
                source_url=meeting.source_page_url,
                payload=payload,
                content_hash=hashlib.sha256(encoded).hexdigest(),
            )
        )
    return records


def _source_record_id(payload: dict[str, Any]) -> str:
    explicit = _string(payload.get("source_record_id") or payload.get("id"))
    if explicit:
        return explicit
    basis = "|".join(
        _string(payload.get(field)) or ""
        for field in (
            "name",
            "day",
            "time",
            "address_line1",
            "city",
            "online_url",
            "row_index",
        )
    )
    if not basis.strip("|"):
        basis = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(basis.encode(), usedforsecurity=False).hexdigest()[:16]


def _string(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None

import hashlib
import json
from typing import Any

import httpx

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.adapters.html_config import configured_selectors, extract_records_from_html
from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence
from app.normalize.schedule import normalize_days, parse_time
from app.sources.registry import (
    COUNTRY_TIMEZONES,
    US_REGION_TIMEZONES,
    Source,
    timezone_for_country_region,
)

US_REGION_ABBREVIATIONS = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District Of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}

CANADA_REGION_ABBREVIATIONS = {
    "AB",
    "BC",
    "MB",
    "NB",
    "NL",
    "NS",
    "NT",
    "NU",
    "ON",
    "PE",
    "QC",
    "SK",
    "YT",
}

MEXICO_REGION_ABBREVIATIONS = {
    "BC": "B.C.",
    "BCS": "B.C.S.",
    "CDMX": "Cdmx",
    "COL": "Colima",
    "GRO": "Guerrero",
    "GTO": "Gto",
    "JAL": "Jalisco",
    "MICH": "Michoacán",
    "NAY": "Nayarit",
    "OAX": "Oax",
    "QR": "Quintana Roo",
    "Q.R": "Quintana Roo",
    "QRO": "Qro",
    "SIN": "Sinaloa",
    "SON": "Sonora",
}


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
        address_line1 = _string(payload.get("address_line1") or payload.get("address"))
        inferred_country, inferred_region = _country_region_from_address(address_line1)
        country = _string(payload.get("country")) or self.source.country
        region = _string(payload.get("region")) or self.source.region
        payload_timezone = _string(payload.get("timezone"))
        timezone = (
            (payload_timezone if payload_timezone != "UTC" else None)
            or self.source.config.get("timezone")
            or timezone_for_country_region(country, region)
            or timezone_for_country_region(inferred_country, region)
            or timezone_for_country_region(inferred_country, inferred_region)
            or "UTC"
        )
        country = country or inferred_country
        region = region or self.source.region or inferred_region
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
            address_line1=address_line1,
            city=_string(payload.get("city")) or self.source.config.get("city"),
            region=region,
            country=country,
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


def _country_region_from_address(address: str | None) -> tuple[str | None, str | None]:
    if not address:
        return None, None
    parts = [part.strip() for part in address.replace("\n", ",").split(",")]
    country = _country_from_address_parts(parts)
    for part in parts:
        tokens = [token.strip(" .").upper() for token in part.split()]
        for token in tokens:
            if country == "United States" and token in US_REGION_ABBREVIATIONS:
                return country or "United States", US_REGION_ABBREVIATIONS[token]
            if token in CANADA_REGION_ABBREVIATIONS:
                return country or "Canada", token
            if token in MEXICO_REGION_ABBREVIATIONS:
                return country or "Mexico", MEXICO_REGION_ABBREVIATIONS[token]
    return country, None


def _country_from_address_parts(parts: list[str]) -> str | None:
    for part in parts:
        normalized = part.casefold()
        if normalized in {"us", "usa", "united states", "united states of america"}:
            return "United States"
        if normalized in COUNTRY_TIMEZONES:
            return part
    if any(part.title() in US_REGION_TIMEZONES for part in parts):
        return "United States"
    return None


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

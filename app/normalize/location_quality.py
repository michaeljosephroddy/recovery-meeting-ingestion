import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.normalize.canonical import CanonicalMeetingCandidate, SnapshotMeeting

COUNTRY_ALIASES: dict[str, str] = {
    "au": "Australia",
    "australia": "Australia",
    "austria": "Austria",
    "brazil": "Brazil",
    "ca": "Canada",
    "canada": "Canada",
    "danmark": "Denmark",
    "dania": "Denmark",
    "denmark": "Denmark",
    "deutschland": "Germany",
    "eire": "Ireland",
    "éire": "Ireland",
    "germany": "Germany",
    "great britain": "United Kingdom",
    "holandia": "Netherlands",
    "ireland": "Ireland",
    "japan": "Japan",
    "nederland": "Netherlands",
    "netherlands": "Netherlands",
    "new zealand": "New Zealand",
    "niemcy": "Germany",
    "norway": "Norway",
    "norwegia": "Norway",
    "poland": "Poland",
    "polska": "Poland",
    "south africa": "South Africa",
    "sweden": "Sweden",
    "szwecja": "Sweden",
    "u.k.": "United Kingdom",
    "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
    "united states": "United States",
    "united states of america": "United States",
    "us": "United States",
    "u.s.a.": "United States",
    "usa": "United States",
    "wielka brytania": "United Kingdom",
}

LOCATION_COUNTRY_ALIASES = {
    alias: country
    for alias, country in COUNTRY_ALIASES.items()
    if alias not in {"au", "ca", "us"}
}
CANONICAL_COUNTRIES = {country.casefold(): country for country in set(COUNTRY_ALIASES.values())}
LOCATION_FIELDS = ("venue_name", "address_line1", "address_line2", "city", "region", "postal_code")
COUNTRY_SEGMENT_FIELDS = ("address_line1", "address_line2", "city", "region", "postal_code")
UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE)
IE_EIRCODE_RE = re.compile(r"\b[AC-FHKNPRTV-Y]\d{2}\s?[0-9AC-FHKNPRTV-Y]{4}\b", re.IGNORECASE)

TIMEZONE_PREFIXES_BY_COUNTRY: dict[str, tuple[str, ...]] = {
    "Australia": ("Australia/",),
    "Austria": ("Europe/Vienna",),
    "Brazil": ("America/",),
    "Canada": ("America/", "Canada/"),
    "Denmark": ("Europe/Copenhagen",),
    "Germany": ("Europe/Berlin",),
    "Ireland": ("Europe/Dublin",),
    "Japan": ("Asia/Tokyo",),
    "Netherlands": ("Europe/Amsterdam",),
    "New Zealand": ("Pacific/Auckland", "Pacific/Chatham"),
    "Norway": ("Europe/Oslo",),
    "Poland": ("Europe/Warsaw",),
    "South Africa": ("Africa/Johannesburg",),
    "Sweden": ("Europe/Stockholm",),
    "United Kingdom": ("Europe/London",),
    "United States": ("America/", "Pacific/Honolulu", "US/"),
}


@dataclass(frozen=True)
class LocationQualityIssueExample:
    fellowship: str
    source_id: str
    source_record_id: str
    name: str
    meeting_type: str
    venue_name: str | None
    address_line1: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country: str | None
    timezones: list[str]
    evidence: dict[str, list[str]]
    source_url: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "fellowship": self.fellowship,
            "source_id": self.source_id,
            "source_record_id": self.source_record_id,
            "name": self.name,
            "meeting_type": self.meeting_type,
            "venue_name": self.venue_name,
            "address_line1": self.address_line1,
            "city": self.city,
            "region": self.region,
            "postal_code": self.postal_code,
            "country": self.country,
            "timezones": self.timezones,
            "evidence": self.evidence,
            "source_url": self.source_url,
        }


@dataclass
class LocationQualityAudit:
    total_meetings: int
    country_aliases: Counter[str] = field(default_factory=Counter)
    issue_counts: Counter[str] = field(default_factory=Counter)
    issue_counts_by_fellowship: Counter[str] = field(default_factory=Counter)
    issue_counts_by_source: Counter[str] = field(default_factory=Counter)
    examples: dict[str, list[LocationQualityIssueExample]] = field(default_factory=dict)

    def add_issue(
        self,
        issue_code: str,
        meeting: SnapshotMeeting,
        evidence: dict[str, list[str]],
        *,
        max_examples: int,
    ) -> None:
        self.issue_counts[issue_code] += 1
        self.issue_counts_by_fellowship[f"{issue_code}:{meeting.fellowship}"] += 1
        self.issue_counts_by_source[f"{issue_code}:{meeting.source_id}"] += 1
        examples = self.examples.setdefault(issue_code, [])
        if len(examples) >= max_examples:
            return
        examples.append(
            LocationQualityIssueExample(
                fellowship=meeting.fellowship,
                source_id=meeting.source_id,
                source_record_id=meeting.source_record_id,
                name=meeting.name,
                meeting_type=meeting.meeting_type,
                venue_name=meeting.venue_name,
                address_line1=meeting.address_line1,
                city=meeting.city,
                region=meeting.region,
                postal_code=meeting.postal_code,
                country=meeting.country,
                timezones=sorted({
                    occurrence.timezone
                    for occurrence in meeting.occurrences
                    if occurrence.timezone
                }),
                evidence=evidence,
                source_url=meeting.source_url,
            )
        )


def normalize_country_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold().strip(" .,")
    if not normalized:
        return None
    return COUNTRY_ALIASES.get(normalized) or CANONICAL_COUNTRIES.get(normalized) or value.strip()


def normalize_candidate_location(
    candidate: CanonicalMeetingCandidate,
) -> CanonicalMeetingCandidate:
    update: dict[str, str | None] = {}
    declared_country = normalize_country_name(candidate.country)
    explicit_countries = _explicit_location_countries(candidate)

    if declared_country != candidate.country:
        update["country"] = declared_country

    if len(explicit_countries) == 1:
        inferred_country = next(iter(explicit_countries))
        if declared_country != inferred_country:
            update["country"] = inferred_country

    next_country = update.get("country", declared_country)
    if next_country:
        for field_name in ("address_line1", "address_line2", "city", "region"):
            normalized_value = _strip_trailing_country_segment(
                getattr(candidate, field_name),
                next_country,
            )
            if normalized_value != getattr(candidate, field_name):
                update[field_name] = normalized_value
        current_region = update.get("region", candidate.region)
        normalized_region = _drop_redundant_country_region(current_region, next_country)
        if normalized_region != current_region:
            update["region"] = normalized_region

    if not update:
        return candidate
    return candidate.model_copy(update=update)


def audit_snapshot_meetings(
    meetings: Sequence[SnapshotMeeting],
    *,
    max_examples_per_issue: int = 5,
) -> LocationQualityAudit:
    audit = LocationQualityAudit(total_meetings=len(meetings))
    for meeting in meetings:
        declared_country = normalize_country_name(meeting.country)
        if meeting.country and declared_country != meeting.country:
            audit.country_aliases[f"{meeting.country}=>{declared_country}"] += 1

        explicit_countries = _explicit_location_countries(meeting)
        if declared_country:
            conflicts = {
                country: evidence
                for country, evidence in explicit_countries.items()
                if country != declared_country
            }
            if conflicts:
                audit.add_issue(
                    "high_confidence_country_conflict",
                    meeting,
                    conflicts,
                    max_examples=max_examples_per_issue,
                )
        elif explicit_countries:
            audit.add_issue(
                "high_confidence_missing_country",
                meeting,
                explicit_countries,
                max_examples=max_examples_per_issue,
            )

        timezone_mismatches = _timezone_country_mismatches(meeting, declared_country)
        if timezone_mismatches:
            audit.add_issue(
                "timezone_country_mismatch",
                meeting,
                {"timezones": timezone_mismatches},
                max_examples=max_examples_per_issue,
            )
    return audit


def _explicit_location_countries(
    meeting: CanonicalMeetingCandidate | SnapshotMeeting,
) -> dict[str, list[str]]:
    countries: dict[str, list[str]] = {}
    for segment in _country_segments(meeting):
        country = LOCATION_COUNTRY_ALIASES.get(segment)
        if country:
            countries.setdefault(country, []).append(segment)

    text = _location_text(meeting)
    if UK_POSTCODE_RE.search(text):
        countries.setdefault("United Kingdom", []).append("uk_postcode")
    if IE_EIRCODE_RE.search(text):
        countries.setdefault("Ireland", []).append("eircode")
    return countries


def _country_segments(meeting: CanonicalMeetingCandidate | SnapshotMeeting) -> list[str]:
    segments: list[str] = []
    for field_name in COUNTRY_SEGMENT_FIELDS:
        value = getattr(meeting, field_name)
        if not value:
            continue
        for segment in re.split(r"[,|\n;]+", value):
            cleaned = segment.strip().casefold().strip(" .")
            if cleaned:
                segments.append(cleaned)
    return segments


def _location_text(meeting: CanonicalMeetingCandidate | SnapshotMeeting) -> str:
    return " | ".join(str(getattr(meeting, field_name) or "") for field_name in LOCATION_FIELDS)


def _drop_redundant_country_region(region: str | None, country: str) -> str | None:
    if not region:
        return region
    region_country = normalize_country_name(region)
    if region_country == country:
        return None
    return region


def _strip_trailing_country_segment(value: str | None, country: str) -> str | None:
    if not value:
        return value
    parts = [part.strip() for part in re.split(r"[,|\n;]+", value) if part.strip()]
    if len(parts) < 2:
        return value
    trailing_country = LOCATION_COUNTRY_ALIASES.get(parts[-1].casefold().strip(" ."))
    if trailing_country != country:
        return value
    stripped = ", ".join(parts[:-1]).strip()
    return stripped or None


def _timezone_country_mismatches(
    meeting: SnapshotMeeting,
    declared_country: str | None,
) -> list[str]:
    if not declared_country:
        return []
    expected_prefixes = TIMEZONE_PREFIXES_BY_COUNTRY.get(declared_country)
    if not expected_prefixes:
        return []

    mismatches: list[str] = []
    for occurrence in meeting.occurrences:
        timezone = occurrence.timezone
        if not any(timezone.startswith(prefix) for prefix in expected_prefixes):
            mismatches.append(timezone)
    return sorted(set(mismatches))

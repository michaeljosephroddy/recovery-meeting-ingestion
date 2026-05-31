import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence, SnapshotMeeting
from app.sources.registry import (
    AUSTRALIA_REGION_TIMEZONES,
    CANADA_REGION_TIMEZONES,
    US_REGION_TIMEZONES,
    Source,
    timezone_for_country_region,
)

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
COUNTRY_SEGMENT_FIELDS = ("address_line1", "address_line2", "region", "postal_code")
COUNTRY_CODES: dict[str, str] = {
    "Australia": "AU",
    "Austria": "AT",
    "Brazil": "BR",
    "Canada": "CA",
    "Denmark": "DK",
    "Germany": "DE",
    "Ireland": "IE",
    "Japan": "JP",
    "Netherlands": "NL",
    "New Zealand": "NZ",
    "Norway": "NO",
    "Poland": "PL",
    "South Africa": "ZA",
    "Sweden": "SE",
    "United Kingdom": "GB",
    "United States": "US",
}
UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE)
IE_EIRCODE_RE = re.compile(r"\b[AC-FHKNPRTV-Y]\d{2}\s?[0-9AC-FHKNPRTV-Y]{4}\b", re.IGNORECASE)
CANADA_POSTAL_RE = re.compile(
    r"\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]\s?\d[ABCEGHJ-NPRSTV-Z]\d\b",
    re.IGNORECASE,
)
US_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
AU_POSTCODE_RE = re.compile(r"\b\d{4}\b")

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
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NL": "Newfoundland And Labrador",
    "NS": "Nova Scotia",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "ON": "Ontario",
    "PE": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "YT": "Yukon",
}
AUSTRALIA_REGION_ABBREVIATIONS = {
    "ACT": "Australian Capital Territory",
    "NSW": "New South Wales",
    "NT": "Northern Territory",
    "QLD": "Queensland",
    "SA": "South Australia",
    "TAS": "Tasmania",
    "VIC": "Victoria",
    "WA": "Western Australia",
}
IRELAND_ADMIN_REGIONS = {
    "all ireland": "All Ireland",
    "antrim": "Antrim",
    "armagh": "Armagh",
    "carlow": "Carlow",
    "cavan": "Cavan",
    "clare": "Clare",
    "cork": "Cork",
    "derry": "Derry",
    "donegal": "Donegal",
    "down": "Down",
    "dublin": "Dublin",
    "dublin north": "Dublin North",
    "dublin south": "Dublin South",
    "fermanagh": "Fermanagh",
    "galway": "Galway",
    "kerry": "Kerry",
    "kildare": "Kildare",
    "kilkenny": "Kilkenny",
    "laois": "Laois",
    "leitrim": "Leitrim",
    "limerick": "Limerick",
    "longford": "Longford",
    "louth": "Louth",
    "mayo": "Mayo",
    "meath": "Meath",
    "monaghan": "Monaghan",
    "offaly": "Offaly",
    "roscommon": "Roscommon",
    "sligo": "Sligo",
    "tipperary": "Tipperary",
    "tyrone": "Tyrone",
    "waterford": "Waterford",
    "westmeath": "Westmeath",
    "wexford": "Wexford",
    "wicklow": "Wicklow",
}
IRELAND_ADMIN_REGION_ALIASES = {
    alias: region
    for name, region in IRELAND_ADMIN_REGIONS.items()
    for alias in (name, f"co {name}", f"co. {name}", f"county {name}")
}
UK_ADMIN_REGIONS = {
    "england": "England",
    "northern ireland": "Northern Ireland",
    "scotland": "Scotland",
    "wales": "Wales",
    "greater london": "Greater London",
    **IRELAND_ADMIN_REGION_ALIASES,
}
REGION_CODES_BY_COUNTRY: dict[str, dict[str, str]] = {
    "United States": {name: abbr for abbr, name in US_REGION_ABBREVIATIONS.items()},
    "Canada": {name: abbr for abbr, name in CANADA_REGION_ABBREVIATIONS.items()},
    "Australia": {name: abbr for abbr, name in AUSTRALIA_REGION_ABBREVIATIONS.items()},
    "United Kingdom": {
        "England": "ENG",
        "Northern Ireland": "NIR",
        "Scotland": "SCT",
        "Wales": "WLS",
    },
}
ADMIN_REGION_ALIASES_BY_COUNTRY: dict[str, dict[str, str]] = {
    "United States": {
        **{name.casefold(): name for name in US_REGION_TIMEZONES},
        **{abbr.casefold(): name for abbr, name in US_REGION_ABBREVIATIONS.items()},
    },
    "Canada": {
        **{name.casefold(): name for name in CANADA_REGION_TIMEZONES},
        **{abbr.casefold(): name for abbr, name in CANADA_REGION_ABBREVIATIONS.items()},
    },
    "Australia": {
        **{name.casefold(): name for name in AUSTRALIA_REGION_TIMEZONES},
        **{abbr.casefold(): name for abbr, name in AUSTRALIA_REGION_ABBREVIATIONS.items()},
    },
    "Ireland": IRELAND_ADMIN_REGION_ALIASES,
    "United Kingdom": UK_ADMIN_REGIONS,
}

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


def country_code_for(country: str | None) -> str | None:
    normalized = normalize_country_name(country)
    if not normalized:
        return None
    return COUNTRY_CODES.get(normalized)


def region_code_for(country: str | None, region: str | None) -> str | None:
    normalized_country = normalize_country_name(country)
    if not normalized_country or not region:
        return None
    normalized_region = _canonical_admin_region(region, normalized_country)
    if not normalized_region:
        return None
    return REGION_CODES_BY_COUNTRY.get(normalized_country, {}).get(normalized_region)


@dataclass(frozen=True)
class AddressLocationEvidence:
    country: str | None = None
    region: str | None = None
    region_index: int | None = None
    region_code: str | None = None
    city: str | None = None
    postal_code: str | None = None
    country_code: str | None = None
    street_address_line1: str | None = None


def normalize_candidate_location(
    candidate: CanonicalMeetingCandidate,
    source: Source | None = None,
) -> CanonicalMeetingCandidate:
    update: dict[str, object] = {}
    raw_location_text = _raw_location_text(candidate)
    declared_country = normalize_country_name(candidate.country)
    explicit_countries = _explicit_location_countries(candidate)
    source_country = normalize_country_name(source.country if source else None)
    source_region = _canonical_admin_region(source.region if source else None, source_country)
    address_evidence = _address_location_evidence(
        candidate,
        country_hint=declared_country or source_country,
    )

    if declared_country != candidate.country:
        update["country"] = declared_country

    if address_evidence.country and declared_country != address_evidence.country:
        update["country"] = address_evidence.country
    elif len(explicit_countries) == 1:
        inferred_country = next(iter(explicit_countries))
        if declared_country != inferred_country:
            update["country"] = inferred_country
    elif not declared_country and source_country:
        update["country"] = source_country

    next_country = _optional_str(update.get("country", declared_country))
    if next_country:
        for field_name in ("address_line1", "address_line2", "city", "region"):
            normalized_value = _strip_trailing_country_segment(
                getattr(candidate, field_name),
                next_country,
            )
            if normalized_value != getattr(candidate, field_name):
                update[field_name] = normalized_value
        current_region = _optional_str(update.get("region", candidate.region))
        normalized_region = _drop_redundant_country_region(current_region, next_country)
        if normalized_region != current_region:
            update["region"] = normalized_region
        current_region = _optional_str(update.get("region", candidate.region))
        next_region = _region_for_country(
            current_region,
            next_country,
            address_evidence=address_evidence,
            source_region=source_region,
        )
        current_city = _optional_str(update.get("city", candidate.city))
        city_region = None
        if _looks_like_admin_area_value(current_city if isinstance(current_city, str) else None):
            city_region = _region_from_city_value(current_city, next_country)
            if not city_region and not next_region:
                city_region = _generic_admin_region_from_city_value(current_city)
        if city_region and (not next_region or _region_from_city_value(next_region, next_country)):
            next_region = city_region
        if next_region != current_region:
            update["region"] = next_region

    current_postal_code = _optional_str(update.get("postal_code", candidate.postal_code))
    if not current_postal_code and address_evidence.postal_code:
        update["postal_code"] = address_evidence.postal_code

    next_country = _optional_str(update.get("country", candidate.country))
    current_region = _optional_str(update.get("region", candidate.region))
    current_postal_code = _optional_str(update.get("postal_code", candidate.postal_code))
    if (
        next_country == "United States"
        and not current_region
        and isinstance(current_postal_code, str)
    ):
        zip_region = _us_region_from_zip(current_postal_code)
        if zip_region:
            update["region"] = zip_region

    current_city = _optional_str(update.get("city", candidate.city))
    next_city = _city_for_candidate(
        current_city,
        address_evidence=address_evidence,
        region=_optional_str(update.get("region", candidate.region)),
    )
    if next_city != current_city:
        update["city"] = next_city

    current_address_line1 = _optional_str(update.get("address_line1", candidate.address_line1))
    if (
        address_evidence.street_address_line1
        and address_evidence.street_address_line1 != current_address_line1
    ):
        update["address_line1"] = address_evidence.street_address_line1

    next_country = _optional_str(update.get("country", candidate.country))
    next_region = _optional_str(update.get("region", candidate.region))
    if isinstance(next_country, str):
        next_country_code = country_code_for(next_country)
        if next_country_code != candidate.country_code:
            update["country_code"] = next_country_code
    if isinstance(next_country, str) and isinstance(next_region, str):
        next_region_code = region_code_for(next_country, next_region)
        if next_region_code != candidate.region_code:
            update["region_code"] = next_region_code

    location_update_keys = {
        "address_line1",
        "address_line2",
        "city",
        "region",
        "postal_code",
        "country",
    }
    if (
        raw_location_text
        and not candidate.raw_location_text
        and update.keys() & location_update_keys
    ):
        update["raw_location_text"] = raw_location_text

    normalized_occurrences = _occurrences_for_location(
        candidate,
        country=next_country if isinstance(next_country, str) else None,
        region=next_region if isinstance(next_region, str) else None,
    )
    if normalized_occurrences != candidate.occurrences:
        update["occurrences"] = normalized_occurrences

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

        if _looks_like_admin_area_value(meeting.city):
            audit.add_issue(
                "city_admin_area",
                meeting,
                {"city": [str(meeting.city)]},
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
    address_parts = _address_parts(meeting)
    text = _location_text(meeting)
    region_context_parts = [*address_parts]
    if meeting.region:
        region_context_parts.append(meeting.region)
    has_us_state_zip = _has_us_region_and_zip(region_context_parts, text)
    for segment in _country_segments(meeting):
        country = LOCATION_COUNTRY_ALIASES.get(segment)
        if country:
            if has_us_state_zip and country != "United States":
                continue
            countries.setdefault(country, []).append(segment)

    if UK_POSTCODE_RE.search(text) and not has_us_state_zip:
        countries.setdefault("United Kingdom", []).append("uk_postcode")
    if IE_EIRCODE_RE.search(text) and not has_us_state_zip:
        countries.setdefault("Ireland", []).append("eircode")
    return countries


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


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


def _raw_location_text(meeting: CanonicalMeetingCandidate | SnapshotMeeting) -> str | None:
    values: list[str] = []
    for field_name in (*LOCATION_FIELDS, "country"):
        value = getattr(meeting, field_name)
        if not value:
            continue
        cleaned = str(value).strip()
        if cleaned and (not values or cleaned != values[-1]):
            values.append(cleaned)
    return " | ".join(values) if values else None


def _drop_redundant_country_region(region: str | None, country: str) -> str | None:
    if not region:
        return region
    region_country = normalize_country_name(region)
    if region_country == country:
        return None
    return region


def _canonical_admin_region(region: str | None, country: str | None) -> str | None:
    if not region or not country:
        return region
    aliases = ADMIN_REGION_ALIASES_BY_COUNTRY.get(country)
    if not aliases:
        return region
    return aliases.get(region.strip().casefold())


def _region_for_country(
    current_region: str | None,
    country: str,
    *,
    address_evidence: AddressLocationEvidence,
    source_region: str | None,
) -> str | None:
    if address_evidence.region and address_evidence.country == country:
        return address_evidence.region
    if canonical := _canonical_admin_region(current_region, country):
        return canonical
    if not current_region and source_region:
        return source_region
    if source_region and country in {"United States", "Canada", "Australia"}:
        return source_region
    if country in {"United States", "Canada", "Australia"} and current_region:
        return None
    return current_region


def _city_for_candidate(
    current_city: str | None,
    *,
    address_evidence: AddressLocationEvidence,
    region: str | None,
) -> str | None:
    if current_city and _looks_like_artifact_location_value(current_city):
        return None
    if _looks_like_admin_area_value(current_city):
        if address_evidence.city and not _looks_like_admin_area_value(address_evidence.city):
            return address_evidence.city
        return None
    if (
        address_evidence.city
        and not current_city
        and not _looks_like_admin_area_value(address_evidence.city)
    ):
        return address_evidence.city
    return current_city


def _region_from_city_value(value: object, country: object) -> str | None:
    if not isinstance(value, str) or not isinstance(country, str):
        return None
    normalized_country = normalize_country_name(country)
    if not normalized_country:
        return None
    return _canonical_admin_region(value, normalized_country)


def _generic_admin_region_from_city_value(value: object) -> str | None:
    if not isinstance(value, str) or not _looks_like_admin_area_value(value):
        return None
    cleaned = value.strip()
    cleaned = re.sub(r"^co\.?\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^county\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned or None


def _looks_like_admin_area_value(value: str | None) -> bool:
    if not value:
        return False
    cleaned = value.strip()
    if cleaned.casefold().startswith("all "):
        return normalize_country_name(cleaned[4:]) is not None
    return bool(
        re.search(
            r"^(?:co\.?\s+|county\s+)|\b(?:county|municipality|province|district|region)\b",
            cleaned,
            flags=re.IGNORECASE,
        )
    )


def _occurrences_for_location(
    candidate: CanonicalMeetingCandidate,
    *,
    country: str | None,
    region: str | None,
) -> list[MeetingOccurrence]:
    expected_timezone = timezone_for_country_region(country, region)
    if not expected_timezone or not country:
        return candidate.occurrences

    occurrences: list[MeetingOccurrence] = []
    changed = False
    for occurrence in candidate.occurrences:
        if _timezone_matches_country(occurrence.timezone, country):
            occurrences.append(occurrence)
            continue
        occurrences.append(occurrence.model_copy(update={"timezone": expected_timezone}))
        changed = True
    return occurrences if changed else candidate.occurrences


def _timezone_matches_country(timezone: str, country: str) -> bool:
    expected_prefixes = TIMEZONE_PREFIXES_BY_COUNTRY.get(country)
    if not expected_prefixes:
        return True
    return any(timezone.startswith(prefix) for prefix in expected_prefixes)


def _looks_like_artifact_location_value(value: str) -> bool:
    cleaned = value.strip().casefold()
    return (
        cleaned
        in {
            "are listed here:",
            "secondary menu",
            "email",
            "not wheelchair accessible",
            "not wheelchair accessible.",
            "wheelchair accessible",
            "wheelchair accessible.",
        }
        or "@" in cleaned
        or cleaned in {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
    )


def _us_region_from_zip(value: str) -> str | None:
    match = US_ZIP_RE.search(value)
    if not match:
        return None
    zip_code = int(match.group(0)[:5])
    if 73000 <= zip_code <= 73199 or 73400 <= zip_code <= 74199 or 74300 <= zip_code <= 74999:
        return "Oklahoma"
    return None


def _address_location_evidence(
    meeting: CanonicalMeetingCandidate | SnapshotMeeting,
    *,
    country_hint: str | None,
) -> AddressLocationEvidence:
    parts = _address_parts(meeting)
    if not parts:
        return AddressLocationEvidence()

    country = _country_from_address(parts)
    text = ", ".join(parts)
    effective_country = country or country_hint
    region, region_index = _region_from_address_parts(parts, effective_country, text)
    if not country:
        country = _country_from_region(region, text)
        if country:
            effective_country = country
    if region and not effective_country:
        effective_country = country
    if region and effective_country and not _canonical_admin_region(region, effective_country):
        region = None
        region_index = None
    postal_code, postal_index = _postal_code_from_address_parts(parts, effective_country)
    city = _city_from_address_parts(parts, region_index, region)
    if not city and postal_code and postal_index is not None:
        city = _city_before_postal_code(parts[postal_index], postal_code)
    street_address_line1 = _street_address_line1_from_address_parts(
        parts,
        location_index=region_index if region_index is not None else postal_index,
        city=city,
    )
    return AddressLocationEvidence(
        country=country,
        region=region,
        region_index=region_index,
        region_code=region_code_for(effective_country, region),
        city=city,
        postal_code=postal_code,
        country_code=country_code_for(effective_country),
        street_address_line1=street_address_line1,
    )


def _address_parts(meeting: CanonicalMeetingCandidate | SnapshotMeeting) -> list[str]:
    text_parts = [meeting.address_line1, meeting.address_line2]
    if meeting.postal_code:
        text_parts.append(meeting.postal_code)
    text = ", ".join(part for part in text_parts if part)
    return [part.strip() for part in re.split(r"[,|\n;]+", text) if part.strip()]


def _postal_code_from_address_parts(
    parts: list[str],
    country: str | None,
) -> tuple[str | None, int | None]:
    country_order = [country] if country else []
    for candidate_country in ("United States", "Canada", "Australia", "United Kingdom", "Ireland"):
        if candidate_country not in country_order:
            country_order.append(candidate_country)

    for candidate_country in [item for item in country_order if item]:
        if candidate_country == "United States":
            postal_code, index = _postal_match(parts, US_ZIP_RE)
            if postal_code:
                return postal_code, index
        if candidate_country == "Canada":
            postal_code, index = _postal_match(parts, CANADA_POSTAL_RE)
            if postal_code:
                return _format_canada_postal_code(postal_code), index
        if candidate_country == "Australia":
            postal_code, index = _postal_match(parts, AU_POSTCODE_RE)
            if postal_code:
                return postal_code, index
        if candidate_country == "United Kingdom":
            postal_code, index = _postal_match(parts, UK_POSTCODE_RE)
            if postal_code:
                return _format_spaced_postal_code(postal_code.upper()), index
        if candidate_country == "Ireland":
            postal_code, index = _postal_match(parts, IE_EIRCODE_RE)
            if postal_code:
                return _format_spaced_postal_code(postal_code.upper()), index
    return None, None


def _postal_match(parts: list[str], postal_re: re.Pattern[str]) -> tuple[str | None, int | None]:
    for index, part in enumerate(parts):
        if match := postal_re.search(part):
            return match.group(0), index
    return None, None


def _format_canada_postal_code(value: str) -> str:
    compact = re.sub(r"\s+", "", value).upper()
    if len(compact) == 6:
        return f"{compact[:3]} {compact[3:]}"
    return value.strip().upper()


def _format_spaced_postal_code(value: str) -> str:
    compact = re.sub(r"\s+", "", value).upper()
    if len(compact) > 3:
        return f"{compact[:-3]} {compact[-3:]}"
    return value.strip().upper()


def _street_address_line1_from_address_parts(
    parts: list[str],
    *,
    location_index: int | None,
    city: str | None,
) -> str | None:
    if location_index is None or location_index <= 0:
        return None
    street_parts = [part.strip() for part in parts[:location_index] if part.strip()]
    if city and street_parts and street_parts[-1].casefold() == city.casefold():
        street_parts.pop()
    street = ", ".join(street_parts).strip()
    if not street or not _looks_like_street_address(street):
        return None
    return street


def _country_from_address(parts: list[str]) -> str | None:
    text = ", ".join(parts)
    for part in reversed(parts):
        normalized = part.strip().casefold().strip(" .")
        country = LOCATION_COUNTRY_ALIASES.get(normalized)
        if country:
            return country
        if normalized in {"usa", "u.s.a.", "united states", "united states of america"}:
            return "United States"
    if UK_POSTCODE_RE.search(text) and not _has_us_region_and_zip(parts, text):
        return "United Kingdom"
    if IE_EIRCODE_RE.search(text) and not _has_us_region_and_zip(parts, text):
        return "Ireland"
    return None


def _region_from_address_parts(
    parts: list[str],
    country: str | None,
    text: str,
) -> tuple[str | None, int | None]:
    country_order = [country] if country else []
    if "United States" not in country_order and _has_us_region_and_zip(parts, text):
        country_order.insert(0, "United States")
    if "Canada" not in country_order and _has_canada_region(parts):
        country_order.append("Canada")
    if "Australia" not in country_order:
        country_order.append("Australia")
    if "United Kingdom" not in country_order:
        country_order.append("United Kingdom")

    for candidate_country in [item for item in country_order if item]:
        aliases = ADMIN_REGION_ALIASES_BY_COUNTRY.get(candidate_country)
        if not aliases:
            continue
        if candidate_country == "United States":
            region, index = _admin_region_from_address_parts(parts, aliases, US_ZIP_RE)
            if region:
                return region, index
            continue
        if candidate_country == "Canada":
            region, index = _admin_region_from_address_parts(parts, aliases, CANADA_POSTAL_RE)
            if region:
                return region, index
            continue
        if candidate_country == "Australia":
            region, index = _admin_region_from_address_parts(parts, aliases, AU_POSTCODE_RE)
            if region:
                return region, index
            continue
        for index, part in enumerate(parts):
            for token in _region_tokens(part):
                if region := aliases.get(token.casefold()):
                    return region, index
    return None, None


def _admin_region_from_address_parts(
    parts: list[str],
    aliases: dict[str, str],
    postal_re: re.Pattern[str],
) -> tuple[str | None, int | None]:
    postal_indexes = [
        index
        for index, part in enumerate(parts)
        if postal_re.search(part) and not _contains_street_suffix(part)
    ]
    for index in postal_indexes:
        for token in _region_tokens(parts[index]):
            if region := aliases.get(token.casefold()):
                return region, index

    whole_region_indexes = [
        index for index, part in enumerate(parts) if _whole_part_is_admin_region(part, aliases)
    ]
    for index in whole_region_indexes:
        if region := aliases.get(parts[index].strip().casefold().strip(" .")):
            return region, index

    for index, part in enumerate(parts):
        if _looks_like_street_address(part):
            continue
        for token in _region_tokens(part):
            if region := aliases.get(token.casefold()):
                return region, index
    return None, None


def _whole_part_is_admin_region(part: str, aliases: dict[str, str]) -> bool:
    return part.strip().casefold().strip(" .") in aliases


def _region_tokens(part: str) -> list[str]:
    tokens = [part.strip(" .")]
    tokens.extend(token.strip(" .") for token in part.split())
    return [token for token in tokens if token]


def _has_us_region_and_zip(parts: list[str], text: str) -> bool:
    if not US_ZIP_RE.search(text):
        return False
    aliases = ADMIN_REGION_ALIASES_BY_COUNTRY["United States"]
    return any(aliases.get(token.casefold()) for part in parts for token in _region_tokens(part))


def _has_canada_region(parts: list[str]) -> bool:
    aliases = ADMIN_REGION_ALIASES_BY_COUNTRY["Canada"]
    return any(aliases.get(token.casefold()) for part in parts for token in _region_tokens(part))


def _country_from_region(region: str | None, text: str) -> str | None:
    if not region:
        return None
    if _canonical_admin_region(region, "Canada") and (
        CANADA_POSTAL_RE.search(text) or not _canonical_admin_region(region, "United States")
    ):
        return "Canada"
    if _canonical_admin_region(region, "United States") and US_ZIP_RE.search(text):
        return "United States"
    if _canonical_admin_region(region, "Australia"):
        return "Australia"
    if _canonical_admin_region(region, "United Kingdom") and UK_POSTCODE_RE.search(text):
        return "United Kingdom"
    return None


def _city_from_address_parts(
    parts: list[str],
    region_index: int | None,
    region: str | None,
) -> str | None:
    if region_index is None:
        return None
    city_in_region_part = _city_before_region_token(parts[region_index], region)
    if city_in_region_part:
        return city_in_region_part
    if region_index <= 0:
        return None
    city = parts[region_index - 1].strip()
    if not city or city.casefold() == (region or "").casefold():
        return None
    if _looks_like_street_address(city):
        return None
    return city


def _city_before_region_token(part: str, region: str | None) -> str | None:
    if not region:
        return None
    aliases = {
        alias
        for country_aliases in ADMIN_REGION_ALIASES_BY_COUNTRY.values()
        for alias, canonical_region in country_aliases.items()
        if canonical_region == region
    }
    for alias in sorted(aliases, key=len, reverse=True):
        match = re.search(rf"\b{re.escape(alias)}\b", part, re.IGNORECASE)
        if not match:
            continue
        city = part[: match.start()].strip(" ,")
        if city.casefold().strip(" .") in {"co", "county"}:
            continue
        if city and not _looks_like_street_address(city):
            return city
    return None


def _city_before_postal_code(part: str, postal_code: str) -> str | None:
    postal_pattern = r"\s*".join(
        re.escape(token) for token in re.split(r"\s+", postal_code.strip()) if token
    )
    match = re.search(postal_pattern, part, re.IGNORECASE) if postal_pattern else None
    if not match:
        return None
    city = part[: match.start()].strip(" ,")
    if not city or _looks_like_street_address(city):
        return None
    return city


def _looks_like_street_address(value: str) -> bool:
    return bool(re.search(r"\d", value)) or _contains_street_suffix(value)


def _contains_street_suffix(value: str) -> bool:
    return bool(
        re.search(
            r"\b(?:st|street|rd|road|ave|avenue|blvd|lane|ln|dr|drive|"
            r"hwy|highway|wy|way)\b",
            value,
            re.I,
        )
    )


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
    if meeting.meeting_type == "online":
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

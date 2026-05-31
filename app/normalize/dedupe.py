import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time

from rapidfuzz import fuzz

from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence

type SemanticKey = tuple[str, str, str, str]
type OccurrenceKey = tuple[int, time, time | None, str]

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_WHITESPACE_RE = re.compile(r"\s+")
_ADDRESS_WORD_REPLACEMENTS = {
    "st": "street",
    "str": "street",
    "rd": "road",
    "ave": "avenue",
    "av": "avenue",
    "blvd": "boulevard",
    "dr": "drive",
    "ln": "lane",
    "ct": "court",
    "pl": "place",
}
_BAD_LOCATION_TEXT = {
    "not wheelchair accessible",
    "not wheelchair accessible.",
    "wheelchair accessible",
    "wheelchair accessible.",
}
_TRAILING_ADMIN_TOKENS = {
    "munster",
    "leinster",
    "ulster",
    "connacht",
}


@dataclass(frozen=True)
class DuplicateCandidate:
    left_source_record_id: str
    right_source_record_id: str
    score: float


@dataclass(frozen=True)
class DuplicateExample:
    fellowship: str
    source_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    name: str
    removed_count: int


@dataclass(frozen=True)
class DuplicateMetrics:
    original_count: int
    consolidated_count: int
    removed_count: int
    exact_occurrence_duplicate_groups_by_fellowship: dict[str, int] = field(default_factory=dict)
    semantic_duplicate_groups_by_fellowship: dict[str, int] = field(default_factory=dict)
    removed_by_fellowship: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ConsolidationResult:
    candidates: list[CanonicalMeetingCandidate]
    metrics: DuplicateMetrics
    examples: list[DuplicateExample] = field(default_factory=list)


def find_duplicate_candidates(
    candidates: list[CanonicalMeetingCandidate],
    threshold: float = 92.0,
) -> list[DuplicateCandidate]:
    duplicates: list[DuplicateCandidate] = []
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1 :]:
            if left.source_record_id == right.source_record_id:
                continue
            if not _same_place(left, right):
                continue
            score = fuzz.token_set_ratio(_dedupe_text(left), _dedupe_text(right))
            if score >= threshold:
                duplicates.append(
                    DuplicateCandidate(
                        left_source_record_id=left.source_record_id,
                        right_source_record_id=right.source_record_id,
                        score=float(score),
                    )
                )
    return duplicates


def consolidate_duplicate_candidates(
    candidates: list[CanonicalMeetingCandidate],
    *,
    max_examples: int = 20,
) -> ConsolidationResult:
    exact_duplicate_groups = _exact_occurrence_duplicate_groups(candidates)
    grouped: dict[SemanticKey, list[CanonicalMeetingCandidate]] = {}
    group_positions: dict[SemanticKey, int] = {}
    ordered_candidates: list[tuple[int, CanonicalMeetingCandidate]] = []
    for index, candidate in enumerate(candidates):
        key = _semantic_key(candidate)
        if key is None:
            ordered_candidates.append((index, candidate))
            continue
        group_positions.setdefault(key, index)
        grouped.setdefault(key, []).append(candidate)

    semantic_groups_by_fellowship: Counter[str] = Counter()
    removed_by_fellowship: Counter[str] = Counter()
    examples: list[DuplicateExample] = []

    for key, group in grouped.items():
        position = group_positions[key]
        if len(group) == 1:
            ordered_candidates.append((position, group[0]))
            continue

        fellowship = group[0].fellowship
        semantic_groups_by_fellowship[fellowship] += 1
        removed_by_fellowship[fellowship] += len(group) - 1
        primary = _primary_candidate(group)
        merged = primary.model_copy(
            update={
                "formats": _merge_formats(group),
                "occurrences": _merge_occurrences(group),
                "last_verified_at": _latest_last_verified_at(group),
            }
        )
        if len(examples) < max_examples:
            examples.append(
                DuplicateExample(
                    fellowship=fellowship,
                    source_ids=tuple(sorted({candidate.source_id for candidate in group})),
                    source_record_ids=tuple(
                        sorted({candidate.source_record_id for candidate in group})
                    ),
                    name=primary.name,
                    removed_count=len(group) - 1,
                )
            )

        ordered_candidates.append((position, merged))

    consolidated = [
        candidate for _position, candidate in sorted(ordered_candidates, key=lambda item: item[0])
    ]
    metrics = DuplicateMetrics(
        original_count=len(candidates),
        consolidated_count=len(consolidated),
        removed_count=len(candidates) - len(consolidated),
        exact_occurrence_duplicate_groups_by_fellowship=dict(exact_duplicate_groups),
        semantic_duplicate_groups_by_fellowship=dict(semantic_groups_by_fellowship),
        removed_by_fellowship=dict(removed_by_fellowship),
    )
    return ConsolidationResult(candidates=consolidated, metrics=metrics, examples=examples)


def _semantic_key(candidate: CanonicalMeetingCandidate) -> SemanticKey | None:
    name_key = _normalize_text(candidate.name)
    if not name_key:
        return None
    place_key = _place_key(candidate)
    if not place_key:
        return None
    return (candidate.fellowship, candidate.meeting_type, name_key, place_key)


def _place_key(candidate: CanonicalMeetingCandidate) -> str | None:
    connection_key = _connection_key(candidate)
    physical_key = _physical_place_key(candidate)
    if physical_key:
        return physical_key
    return connection_key


def _connection_key(candidate: CanonicalMeetingCandidate) -> str | None:
    values = []
    if candidate.online_url is not None:
        values.append(str(candidate.online_url))
    if candidate.phone_join_info:
        values.append(candidate.phone_join_info)
    normalized = _normalize_text(" ".join(values))
    return f"connection:{normalized}" if normalized else None


def _physical_place_key(candidate: CanonicalMeetingCandidate) -> str | None:
    address = _normalize_address(candidate.address_line1)
    address2 = _normalize_address(candidate.address_line2)
    city = _normalize_location_field(candidate.city)
    region = _normalize_location_field(candidate.region_code or candidate.region)
    postal_code = _normalize_text(candidate.postal_code)
    country = _normalize_location_field(candidate.country_code or candidate.country)

    if address:
        pieces = [address, address2, city, postal_code, country]
    elif candidate.venue_name:
        pieces = [_normalize_location_field(candidate.venue_name), city, region, country]
    else:
        pieces = [city, region, country]

    normalized = " ".join(piece for piece in pieces if piece)
    text_key = _normalize_text(normalized)
    if text_key:
        return text_key

    latitude = round(candidate.latitude, 3) if candidate.latitude is not None else None
    longitude = round(candidate.longitude, 3) if candidate.longitude is not None else None
    if latitude is not None and longitude is not None and not candidate.is_approximate_location:
        return f"geo:{latitude}:{longitude}"
    return None


def _normalize_location_field(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.casefold() in _BAD_LOCATION_TEXT:
        return None
    return _normalize_text(cleaned)


def _normalize_address(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    if len(parts) > 1:
        cleaned = " ".join(parts[:2])
    normalized = _normalize_text(cleaned)
    if not normalized:
        return None
    tokens = [token for token in normalized.split() if token not in _TRAILING_ADMIN_TOKENS]
    return " ".join(tokens)


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    tokens = []
    for token in _TOKEN_RE.findall(value.casefold()):
        tokens.append(_ADDRESS_WORD_REPLACEMENTS.get(token, token))
    return _WHITESPACE_RE.sub(" ", " ".join(tokens)).strip()


def _primary_candidate(
    candidates: list[CanonicalMeetingCandidate],
) -> CanonicalMeetingCandidate:
    return sorted(candidates, key=_primary_candidate_sort_key)[0]


def _primary_candidate_sort_key(candidate: CanonicalMeetingCandidate) -> tuple[object, ...]:
    return (
        -_candidate_completeness_score(candidate),
        candidate.is_approximate_location,
        candidate.source_id,
        candidate.source_record_id,
    )


def _candidate_completeness_score(candidate: CanonicalMeetingCandidate) -> int:
    fields = (
        candidate.venue_name,
        candidate.address_line1,
        candidate.address_line2,
        candidate.city,
        candidate.region,
        candidate.region_code,
        candidate.postal_code,
        candidate.country,
        candidate.country_code,
        candidate.online_url,
        candidate.phone_join_info,
        candidate.language,
        candidate.accessibility_notes,
    )
    score = sum(1 for value in fields if value)
    score += len(candidate.formats)
    score += len(candidate.occurrences)
    if candidate.latitude is not None and candidate.longitude is not None:
        score += 2
    if candidate.last_verified_at is not None:
        score += 1
    return score


def _merge_occurrences(
    candidates: list[CanonicalMeetingCandidate],
) -> list[MeetingOccurrence]:
    occurrence_map: dict[OccurrenceKey, MeetingOccurrence] = {}
    for candidate in candidates:
        for occurrence in candidate.occurrences:
            occurrence_map.setdefault(_occurrence_key(occurrence), occurrence)
    return [
        occurrence_map[key]
        for key in sorted(
            occurrence_map,
            key=lambda key: (key[0], key[1], key[2] or time.max, key[3]),
        )
    ]


def _occurrence_key(occurrence: MeetingOccurrence) -> OccurrenceKey:
    return (
        occurrence.day_of_week,
        occurrence.start_time_local,
        occurrence.end_time_local,
        occurrence.timezone,
    )


def _merge_formats(candidates: list[CanonicalMeetingCandidate]) -> list[str]:
    return sorted(
        {
            normalized
            for candidate in candidates
            for value in candidate.formats
            if (normalized := value.strip())
        },
        key=str.casefold,
    )


def _latest_last_verified_at(candidates: list[CanonicalMeetingCandidate]) -> datetime | None:
    values = [candidate.last_verified_at for candidate in candidates if candidate.last_verified_at]
    return max(values) if values else None


def _exact_occurrence_duplicate_groups(
    candidates: list[CanonicalMeetingCandidate],
) -> Counter[str]:
    groups: Counter[tuple[str, str, str, str, OccurrenceKey]] = Counter()
    for candidate in candidates:
        semantic_key = _semantic_key(candidate)
        if semantic_key is None:
            continue
        for occurrence in candidate.occurrences:
            groups[(*semantic_key, _occurrence_key(occurrence))] += 1
    duplicates: Counter[str] = Counter()
    for key, count in groups.items():
        if count > 1:
            duplicates[key[0]] += 1
    return duplicates


def _same_place(left: CanonicalMeetingCandidate, right: CanonicalMeetingCandidate) -> bool:
    if left.city and right.city and left.city.casefold() != right.city.casefold():
        return False
    return not (
        left.country
        and right.country
        and left.country.casefold() != right.country.casefold()
    )


def _dedupe_text(candidate: CanonicalMeetingCandidate) -> str:
    return " ".join(
        value or ""
        for value in (
            candidate.name,
            candidate.venue_name,
            candidate.address_line1,
            candidate.city,
            candidate.country,
        )
    )

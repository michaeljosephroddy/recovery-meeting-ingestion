import re
from dataclasses import dataclass

from app.normalize.canonical import CanonicalMeetingCandidate


@dataclass(frozen=True)
class ReviewFlag:
    code: str
    severity: str
    message: str
    source_record_id: str | None = None


def flags_for_candidate(candidate: CanonicalMeetingCandidate) -> list[ReviewFlag]:
    flags: list[ReviewFlag] = []
    if any(occurrence.timezone == "UTC" for occurrence in candidate.occurrences):
        flags.append(
            ReviewFlag(
                code="missing_timezone",
                severity="warning",
                message="candidate uses fallback UTC timezone",
                source_record_id=candidate.source_record_id,
            )
        )
    if _looks_like_location_text_artifact(candidate):
        flags.append(
            ReviewFlag(
                code="location_text_artifact",
                severity="error",
                message=(
                    "candidate appears to be navigation, schedule, or contact text "
                    "rather than a meeting"
                ),
                source_record_id=candidate.source_record_id,
            )
        )
    return flags


def flag_source_drop(previous_active_count: int, current_active_count: int) -> ReviewFlag | None:
    if previous_active_count <= 0:
        return None
    dropped = previous_active_count - current_active_count
    if dropped / previous_active_count > 0.20:
        return ReviewFlag(
            code="source_large_drop",
            severity="error",
            message="source dropped more than 20 percent of previous active meetings",
        )
    return None


DAY_NAMES = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}
ARTIFACT_VALUES = {
    "are listed here:",
    "email",
    "secondary menu",
    "printable meeting schedule",
    "time:",
}
ARTIFACT_PHRASES = {
    "in-person + online meetings today",
    "time town meeting location address type",
    "wordfence is a security plugin",
    "wordfence's blocking tools",
    "visit wordfence.com",
}


def _looks_like_location_text_artifact(candidate: CanonicalMeetingCandidate) -> bool:
    values = {
        "name": candidate.name,
        "venue_name": candidate.venue_name,
        "city": candidate.city,
        "address_line1": candidate.address_line1,
    }
    for field, value in values.items():
        if not value:
            continue
        cleaned = value.strip().casefold()
        if len(cleaned) > 500:
            return True
        if field in {"city", "address_line1"} and len(cleaned) > 200:
            return True
        if cleaned in ARTIFACT_VALUES:
            return True
        if cleaned == "about wordfence":
            return True
        if any(phrase in cleaned for phrase in ARTIFACT_PHRASES):
            return True
        if field in {"name", "city"} and cleaned in DAY_NAMES:
            return True
        if field == "city" and re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value):
            return True
        if field == "address_line1" and cleaned.startswith("****meeting time change"):
            return True
    return False

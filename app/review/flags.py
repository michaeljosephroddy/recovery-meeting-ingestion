import re
from dataclasses import dataclass

from app.normalize.canonical import CanonicalMeetingCandidate

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+?\d[\d .()/-]{7,}\d)\b")
ONLINE_CREDENTIAL_RE = re.compile(
    r"\b(?:meeting\s*id|id|passcode|password|pwd|hasło|haslo)\s*[:#]?\s*\S+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReviewFlag:
    code: str
    severity: str
    message: str
    source_record_id: str | None = None


def flags_for_candidate(candidate: CanonicalMeetingCandidate) -> list[ReviewFlag]:
    flags: list[ReviewFlag] = []
    notes = " ".join(
        value
        for value in (
            candidate.accessibility_notes,
            candidate.phone_join_info,
        )
        if value
    )
    contact_notes = ONLINE_CREDENTIAL_RE.sub(" ", notes)
    if EMAIL_RE.search(contact_notes) or PHONE_RE.search(contact_notes):
        flags.append(
            ReviewFlag(
                code="possible_personal_contact",
                severity="warning",
                message="candidate contains possible personal email or phone information",
                source_record_id=candidate.source_record_id,
            )
        )
    if any(occurrence.timezone == "UTC" for occurrence in candidate.occurrences):
        flags.append(
            ReviewFlag(
                code="missing_timezone",
                severity="warning",
                message="candidate uses fallback UTC timezone",
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

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

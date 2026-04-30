from dataclasses import dataclass

from rapidfuzz import fuzz

from app.normalize.canonical import CanonicalMeetingCandidate


@dataclass(frozen=True)
class DuplicateCandidate:
    left_source_record_id: str
    right_source_record_id: str
    score: float


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

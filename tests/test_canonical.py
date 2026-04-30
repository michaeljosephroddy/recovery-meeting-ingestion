import pytest
from pydantic import ValidationError

from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence


def test_canonical_candidate_accepts_physical_meeting() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id="aa-ie",
        source_record_id="daily-reflection",
        source_url="https://example.org/meetings.json",
        name="Daily Reflection",
        meeting_type="in_person",
        address_line1="1 Main Street",
        city="Dublin",
        country="IE",
        occurrences=[
            MeetingOccurrence(
                day_of_week=1,
                start_time_local="19:30",
                timezone="Europe/Dublin",
            )
        ],
    )

    assert candidate.occurrences[0].day_of_week == 1
    assert candidate.occurrences[0].start_time_local.hour == 19


def test_canonical_candidate_rejects_missing_location_and_connection() -> None:
    with pytest.raises(ValidationError):
        CanonicalMeetingCandidate(
            fellowship="aa",
            source_id="aa-ie",
            source_record_id="bad",
            source_url="https://example.org/meetings.json",
            name="Bad Record",
        )


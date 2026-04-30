from app.normalize.canonical import CanonicalMeetingCandidate
from app.normalize.dedupe import find_duplicate_candidates


def test_find_duplicate_candidates_scores_same_place_meetings() -> None:
    first = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id="aa-feed",
        source_record_id="one",
        source_url="https://example.org/meetings.json",
        name="Daily Reflection Group",
        meeting_type="in_person",
        venue_name="Community Hall",
        address_line1="10 Main Street",
        city="Dublin",
        country="IE",
    )
    second = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id="aa-feed",
        source_record_id="two",
        source_url="https://example.org/meetings.json",
        name="Daily Reflections",
        meeting_type="in_person",
        venue_name="Community Hall",
        address_line1="10 Main St",
        city="Dublin",
        country="IE",
    )

    duplicates = find_duplicate_candidates([first, second], threshold=80)

    assert len(duplicates) == 1
    assert duplicates[0].left_source_record_id == "one"
    assert duplicates[0].right_source_record_id == "two"

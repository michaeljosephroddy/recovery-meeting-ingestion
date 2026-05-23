from app.export.snapshot import build_snapshot
from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence
from app.review.flags import flag_source_drop, flags_for_candidate


def test_review_flags_sensitive_contact_and_missing_timezone() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id="aa-online",
        source_record_id="online",
        source_url="https://example.org/meetings.json",
        name="Online Meeting",
        meeting_type="online",
        online_url="https://zoom.example.org/j/123",
        phone_join_info="Passcode: secret contact 555-123-4567",
        occurrences=[MeetingOccurrence(day_of_week=0, start_time_local="12:00", timezone="UTC")],
    )

    codes = {flag.code for flag in flags_for_candidate(candidate)}
    assert "possible_personal_contact" in codes
    assert "possible_private_online_credential" in codes
    assert "missing_timezone" in codes


def test_review_flags_do_not_treat_meeting_id_as_personal_phone() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="ca",
        source_id="ca-online",
        source_record_id="online",
        source_url="https://example.org/meetings",
        name="Online Meeting",
        meeting_type="online",
        phone_join_info="Zoom: Meeting ID: 263 748 3832 Haslo: Nadzieja",
        occurrences=[
            MeetingOccurrence(day_of_week=1, start_time_local="08:00", timezone="Europe/Warsaw")
        ],
    )

    codes = {flag.code for flag in flags_for_candidate(candidate)}
    assert "possible_private_online_credential" in codes
    assert "possible_personal_contact" not in codes


def test_review_flags_source_drop_over_twenty_percent() -> None:
    flag = flag_source_drop(previous_active_count=100, current_active_count=79)

    assert flag is not None
    assert flag.code == "source_large_drop"


def test_snapshot_excludes_raw_payloads() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id="aa-ie",
        source_record_id="daily-reflection",
        source_url="https://example.org/meetings.json",
        name="Daily Reflection",
        meeting_type="in_person",
        address_line1="1 Main Street",
        city="Dublin",
        occurrences=[
            MeetingOccurrence(day_of_week=1, start_time_local="19:30", timezone="Europe/Dublin")
        ],
    )
    snapshot = build_snapshot([candidate])
    dumped = snapshot.model_dump()

    assert "payload" not in str(dumped)
    assert dumped["meetings"][0]["source_record_id"] == "daily-reflection"

from app.export.snapshot import build_snapshot
from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence
from app.review.flags import flag_source_drop, flags_for_candidate


def test_review_flags_allow_listed_contact_info_and_flag_missing_timezone() -> None:
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
    assert "possible_personal_contact" not in codes
    assert "possible_private_online_credential" not in codes
    assert "missing_timezone" in codes


def test_review_flags_do_not_treat_meeting_contact_or_credentials_as_review_noise() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="ca",
        source_id="ca-online",
        source_record_id="online",
        source_url="https://example.org/meetings",
        name="Online Meeting",
        meeting_type="online",
        phone_join_info=(
            "Zoom: Meeting ID: 263 748 3832 Haslo: Nadzieja "
            "Contact group@example.org or 555-123-4567"
        ),
        occurrences=[
            MeetingOccurrence(day_of_week=1, start_time_local="08:00", timezone="Europe/Warsaw")
        ],
    )

    codes = {flag.code for flag in flags_for_candidate(candidate)}
    assert "possible_private_online_credential" not in codes
    assert "possible_personal_contact" not in codes


def test_review_flags_allow_zoom_url() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id="aa-online",
        source_record_id="online",
        source_url="https://example.org/meetings",
        name="Online Meeting",
        meeting_type="online",
        online_url="https://zoom.us/j/83622389914",
        occurrences=[
            MeetingOccurrence(day_of_week=1, start_time_local="08:00", timezone="America/New_York")
        ],
    )

    codes = {flag.code for flag in flags_for_candidate(candidate)}
    assert "possible_personal_contact" not in codes


def test_review_flags_block_schedule_navigation_artifact() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="na",
        source_id="na-24725a7be4e0",
        source_record_id="4e9023a7cbc6c484",
        source_url="https://www.gtascna.org/home/meetings",
        name="PRINTABLE MEETING SCHEDULE",
        meeting_type="in_person",
        venue_name=(
            "NA Virtual Meetings are listed here: Virtual-NA.org or nastuff.com "
            "(includes instructions on how to attend the meetings.)"
        ),
        city="Greater London",
        region="Ontario",
        country="Canada",
        occurrences=[
            MeetingOccurrence(day_of_week=1, start_time_local="19:00", timezone="America/Toronto")
        ],
    )

    flags = flags_for_candidate(candidate)

    assert any(
        flag.code == "location_text_artifact" and flag.severity == "error"
        for flag in flags
    )


def test_review_flags_block_wordfence_security_artifact() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id="aa-546062fcac69",
        source_record_id="57c279e7c33cf92e",
        source_url="https://aadistrict11.ca/meetings/",
        name="Time:",
        meeting_type="in_person",
        venue_name=(
            "You can also read the documentation to learn about Wordfence's blocking "
            "tools, or visit wordfence.com to learn more about Wordfence."
        ),
        address_line1=(
            "Wordfence is a security plugin installed on over 5 million WordPress sites. "
            "The owner of this site is using Wordfence to manage access to their site."
        ),
        city="About Wordfence",
        region="ON",
        country="Canada",
        occurrences=[
            MeetingOccurrence(day_of_week=1, start_time_local="19:00", timezone="America/Toronto")
        ],
    )

    flags = flags_for_candidate(candidate)

    assert any(
        flag.code == "location_text_artifact" and flag.severity == "error"
        for flag in flags
    )


def test_review_flags_block_time_label_as_meeting_name() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id="aa-4350f72ee9f4",
        source_record_id="f7677adb55d30808",
        source_url="https://aaorg.kz/meetings/",
        name="Time:",
        meeting_type="in_person",
        address_line1="+7 707-135-03-05",
        country="Kazakhstan",
        occurrences=[
            MeetingOccurrence(day_of_week=6, start_time_local="09:00", timezone="Asia/Almaty")
        ],
    )

    flags = flags_for_candidate(candidate)

    assert any(
        flag.code == "location_text_artifact" and flag.severity == "error"
        for flag in flags
    )


def test_review_flags_block_schedule_table_collapsed_into_city() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id="aa-5b043cc2986f",
        source_record_id="716475a6b88fbb25",
        source_url="http://www.aaworcester.org/meetinglist.aspx?grp=wai",
        name="5:00A",
        meeting_type="in_person",
        venue_name="Bellingham",
        address_line1="Tune Up",
        city=(
            "(99) In-Person + OnLine Meetings Today Time Town Meeting Location "
            "Address Type 5:00A Bellingham Tune Up How It Works Club "
            "176 Mechanic St CDMH 6:30A Bellingham AA Awakenings How It Works Club"
        ),
        region="Massachusetts",
        country="United States",
    )

    flags = flags_for_candidate(candidate)

    assert any(
        flag.code == "location_text_artifact" and flag.severity == "error"
        for flag in flags
    )


def test_review_flags_block_schedule_table_collapsed_into_name() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id="aa-78a768b03fa2",
        source_record_id="c3b8114faea5ea98",
        source_url="https://www.pghaa.org/meetings",
        name=(
            "Sunday 7:00 AM NORTH PARK EARLY SUNDAY Open Speaker Map This Location "
            "St Martha`s & Mary Parish 2554 Wildwood Rd ALLISON PARK No Smoking "
        )
        * 6,
        meeting_type="in_person",
        venue_name="Map This Location",
        address_line1="Faith United Pres. Church",
        city="BUTLER",
        region="Pennsylvania",
        country="United States",
    )

    flags = flags_for_candidate(candidate)

    assert any(
        flag.code == "location_text_artifact" and flag.severity == "error"
        for flag in flags
    )


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


def test_snapshot_normalizes_location_country_before_export() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id="aa-c592e77d0762",
        source_record_id="9619",
        source_url="https://example.org/meetings.json",
        name="World's End (UK)",
        meeting_type="hybrid",
        venue_name="Virtual Meeting (Hosted by CAIG)",
        address_line1="London, UK",
        region="Chelsea London, UK",
        country="United States",
        occurrences=[
            MeetingOccurrence(day_of_week=1, start_time_local="19:30", timezone="Europe/London")
        ],
    )

    snapshot = build_snapshot([candidate])

    assert snapshot.meetings[0].country == "United Kingdom"
    assert snapshot.meetings[0].address_line1 == "London"
    assert snapshot.meetings[0].region == "Chelsea London"


def test_snapshot_consolidates_na_dingle_across_overlapping_sources() -> None:
    candidates = [
        CanonicalMeetingCandidate(
            fellowship="na",
            source_id="na-2d0fad4641a8",
            source_record_id="5",
            source_url="https://www.na-ireland.org/na-meetings/north/",
            name="Dingle Online and Physically Open",
            meeting_type="hybrid",
            venue_name="Temporary venue, in a tiny extension on the left side of the church",
            address_line1="off Green St, Dingle, Munster",
            country="Ireland",
            occurrences=[
                MeetingOccurrence(
                    day_of_week=2,
                    start_time_local="19:30",
                    timezone="Europe/Dublin",
                )
            ],
        ),
        CanonicalMeetingCandidate(
            fellowship="na",
            source_id="na-565ff8e141b7",
            source_record_id="314",
            source_url="https://www.na-ireland.org/na-meetings/west/",
            name="Dingle Online and Physically Open",
            meeting_type="hybrid",
            venue_name="Temporary venue, in a tiny extension on the left side of the church",
            address_line1="off Green Street, Dingle",
            country="Ireland",
            occurrences=[
                MeetingOccurrence(
                    day_of_week=5,
                    start_time_local="20:30",
                    timezone="Europe/Dublin",
                )
            ],
        ),
    ]

    snapshot = build_snapshot(candidates)

    assert len(snapshot.meetings) == 1
    assert snapshot.meetings[0].source_id == "na-2d0fad4641a8"
    assert [
        (occurrence.day_of_week, str(occurrence.start_time_local))
        for occurrence in snapshot.meetings[0].occurrences
    ] == [(2, "19:30:00"), (5, "20:30:00")]

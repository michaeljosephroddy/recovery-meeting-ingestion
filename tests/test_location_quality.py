from app.export.snapshot import build_snapshot
from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence, SnapshotMeeting
from app.normalize.location_quality import audit_snapshot_meetings, normalize_candidate_location


def occurrence(timezone: str = "Europe/London") -> MeetingOccurrence:
    return MeetingOccurrence(day_of_week=1, start_time_local="19:30", timezone=timezone)


def candidate(**overrides: object) -> CanonicalMeetingCandidate:
    data: dict[str, object] = {
        "fellowship": "aa",
        "source_id": "aa-test",
        "source_record_id": "record-1",
        "source_url": "https://example.org/meetings",
        "name": "Test Meeting",
        "meeting_type": "in_person",
        "address_line1": "1 Main Street",
        "country": "United States",
        "occurrences": [occurrence("America/New_York")],
    }
    data.update(overrides)
    return CanonicalMeetingCandidate(**data)


def test_normalize_candidate_location_fixes_london_uk_country_conflict() -> None:
    normalized = normalize_candidate_location(
        candidate(
            source_id="aa-c592e77d0762",
            source_record_id="9619",
            name="World's End (UK)",
            meeting_type="hybrid",
            venue_name="Virtual Meeting (Hosted by CAIG)",
            address_line1="London, UK",
            region="Chelsea London, UK",
            country="United States",
            occurrences=[occurrence("Europe/London")],
        )
    )

    assert normalized.country == "United Kingdom"
    assert normalized.address_line1 == "London"
    assert normalized.region == "Chelsea London"


def test_normalize_candidate_location_fills_missing_country_from_address_segment() -> None:
    normalized = normalize_candidate_location(
        candidate(
            address_line1="1-chōme-27-1 Deiki, Yokohama, Kanagawa 236-0021, Japan",
            region="Tokyo",
            country=None,
            occurrences=[occurrence("Asia/Tokyo")],
        )
    )

    assert normalized.country == "Japan"


def test_normalize_candidate_location_canonicalizes_country_alias() -> None:
    normalized = normalize_candidate_location(candidate(country="USA"))

    assert normalized.country == "United States"


def test_normalize_candidate_location_drops_redundant_country_region() -> None:
    normalized = normalize_candidate_location(
        candidate(
            address_line1="Malakkastraat 6, Utrecht, Holandia",
            region="Holandia",
            country="Poland",
            occurrences=[occurrence("Europe/Amsterdam")],
        )
    )

    assert normalized.country == "Netherlands"
    assert normalized.address_line1 == "Malakkastraat 6, Utrecht"
    assert normalized.region is None


def test_location_audit_does_not_treat_street_name_as_country_conflict() -> None:
    snapshot = build_snapshot(
        [
            candidate(
                address_line1="Ireland St, Bright VIC 3741, Australia",
                region="VIC",
                country="Australia",
                occurrences=[occurrence("Australia/Melbourne")],
            )
        ]
    )

    audit = audit_snapshot_meetings(snapshot.meetings)

    assert audit.issue_counts["high_confidence_country_conflict"] == 0


def test_location_audit_reports_raw_conflicts_and_missing_countries() -> None:
    wrong_country = SnapshotMeeting(
        fellowship="aa",
        source_id="aa-test",
        source_record_id="wrong-country",
        source_url="https://example.org/meetings",
        name="Wrong Country",
        meeting_type="in_person",
        address_line1="London, UK",
        country="United States",
        is_approximate_location=False,
        formats=[],
        occurrences=[occurrence("Europe/London")],
    )
    missing_country = SnapshotMeeting(
        fellowship="aa",
        source_id="aa-test",
        source_record_id="missing-country",
        source_url="https://example.org/meetings",
        name="Missing Country",
        meeting_type="in_person",
        address_line1="Hibberson St, Gungahlin ACT 2912, Australia",
        region="ACT",
        is_approximate_location=False,
        formats=[],
        occurrences=[occurrence("Australia/Sydney")],
    )

    audit = audit_snapshot_meetings([wrong_country, missing_country])

    assert audit.issue_counts["high_confidence_country_conflict"] == 1
    assert audit.issue_counts["high_confidence_missing_country"] == 1


def test_build_snapshot_removes_auditable_country_issues_by_normalizing() -> None:
    snapshot = build_snapshot(
        [
            candidate(
                source_record_id="wrong-country",
                address_line1="London, UK",
                country="United States",
                occurrences=[occurrence("Europe/London")],
            ),
            candidate(
                source_record_id="missing-country",
                address_line1="Hibberson St, Gungahlin ACT 2912, Australia",
                region="ACT",
                country=None,
                occurrences=[occurrence("Australia/Sydney")],
            ),
        ]
    )

    audit = audit_snapshot_meetings(snapshot.meetings)

    assert audit.issue_counts["high_confidence_country_conflict"] == 0
    assert audit.issue_counts["high_confidence_missing_country"] == 0

from app.export.snapshot import build_snapshot
from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence, SnapshotMeeting
from app.normalize.location_quality import audit_snapshot_meetings, normalize_candidate_location
from app.sources.registry import AdapterType, Source, SourceType


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


def source(**overrides: object) -> Source:
    data: dict[str, object] = {
        "id": "aa-test",
        "fellowship": "aa",
        "name": "Test Source",
        "url": "https://example.org/meetings",
        "country": "United States",
        "region": "California",
        "source_type": SourceType.LOCAL_SERVICE_BODY,
        "adapter_type": AdapterType.STATIC_HTML,
    }
    data.update(overrides)
    return Source(**data)


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


def test_normalize_candidate_location_preserves_london_ontario_canada() -> None:
    normalized = normalize_candidate_location(
        candidate(
            fellowship="na",
            city="London",
            region="ON",
            country="ca",
            address_line1=None,
            venue_name="Recovery Lounge",
            occurrences=[occurrence("America/Toronto")],
        )
    )

    assert normalized.city == "London"
    assert normalized.region == "Ontario"
    assert normalized.country == "Canada"


def test_normalize_candidate_location_preserves_greater_london_ontario_canada() -> None:
    normalized = normalize_candidate_location(
        candidate(
            fellowship="na",
            city="Greater London",
            region="Ontario",
            country="Canada",
            address_line1=None,
            venue_name="NA Virtual Meetings",
            occurrences=[occurrence("America/Toronto")],
        )
    )

    assert normalized.city == "Greater London"
    assert normalized.region == "Ontario"
    assert normalized.country == "Canada"


def test_build_snapshot_preserves_greater_london_ontario_canada_with_codes() -> None:
    snapshot = build_snapshot(
        [
            candidate(
                fellowship="na",
                city="Greater London",
                region="Ontario",
                country="Canada",
                address_line1=None,
                venue_name="NA Virtual Meetings",
                occurrences=[occurrence("America/Toronto")],
            )
        ]
    )

    meeting = snapshot.meetings[0]

    assert meeting.city == "Greater London"
    assert meeting.region == "Ontario"
    assert meeting.region_code == "ON"
    assert meeting.country == "Canada"
    assert meeting.country_code == "CA"


def test_normalize_candidate_location_fixes_timezone_after_country_region_disambiguation() -> None:
    normalized = normalize_candidate_location(
        candidate(
            source_id="aa-08512eb5f89d",
            address_line1="6 Gap Rd, The Gap NT 0870",
            region="NT",
            country="Australia",
            occurrences=[occurrence("America/Yellowknife")],
        )
    )

    assert normalized.region == "Northern Territory"
    assert normalized.country == "Australia"
    assert normalized.occurrences[0].timezone == "Australia/Darwin"


def test_build_snapshot_extracts_structured_australian_address_parts() -> None:
    snapshot = build_snapshot(
        [
            candidate(
                source_id="aa-08512eb5f89d",
                address_line1="6 Gap Rd, The Gap NT 0870",
                region="NT",
                country="Australia",
                occurrences=[occurrence("America/Yellowknife")],
            )
        ]
    )

    meeting = snapshot.meetings[0]

    assert meeting.address_line1 == "6 Gap Rd"
    assert meeting.city == "The Gap"
    assert meeting.region == "Northern Territory"
    assert meeting.region_code == "NT"
    assert meeting.postal_code == "0870"
    assert meeting.country == "Australia"
    assert meeting.country_code == "AU"
    assert meeting.occurrences[0].timezone == "Australia/Darwin"


def test_normalize_candidate_location_does_not_use_australian_state_name_in_street() -> None:
    normalized = normalize_candidate_location(
        candidate(
            address_line1="6 Victoria Hwy, Katherine South NT 0850",
            region="NT",
            country="Australia",
            occurrences=[occurrence("America/Yellowknife")],
        )
    )

    assert normalized.city == "Katherine South"
    assert normalized.region == "Northern Territory"
    assert normalized.occurrences[0].timezone == "Australia/Darwin"


def test_normalize_candidate_location_uses_us_state_over_city_region_leak() -> None:
    normalized = normalize_candidate_location(
        candidate(
            address_line1="810 E Princeton St, Ontario, CA 91764, USA",
            city=None,
            region="Ontario",
            country="United States",
            occurrences=[occurrence("America/Los_Angeles")],
        )
    )

    assert normalized.city == "Ontario"
    assert normalized.region == "California"
    assert normalized.country == "United States"


def test_build_snapshot_extracts_structured_us_address_parts() -> None:
    snapshot = build_snapshot(
        [
            candidate(
                address_line1="810 E Princeton St, Ontario, CA 91764, USA",
                city=None,
                region="Ontario",
                country="United States",
                occurrences=[occurrence("America/Los_Angeles")],
            )
        ]
    )

    meeting = snapshot.meetings[0]

    assert meeting.address_line1 == "810 E Princeton St"
    assert meeting.city == "Ontario"
    assert meeting.region == "California"
    assert meeting.region_code == "CA"
    assert meeting.postal_code == "91764"
    assert meeting.country == "United States"
    assert meeting.country_code == "US"

    normalized = normalize_candidate_location(
        candidate(
            address_line1="810 E Princeton St, Ontario, CA 91764, USA",
            city=None,
            region="Ontario",
            country="United States",
            occurrences=[occurrence("America/Los_Angeles")],
        )
    )
    assert normalized.raw_location_text == "810 E Princeton St, Ontario, CA 91764, USA | Ontario | United States"


def test_normalize_candidate_location_does_not_use_us_state_name_in_street() -> None:
    normalized = normalize_candidate_location(
        candidate(
            address_line1="298 Washington St, Gloucester, MA 01930",
            city=None,
            region="Washington",
            country="United States",
            occurrences=[occurrence("America/New_York")],
        )
    )

    assert normalized.city == "Gloucester"
    assert normalized.region == "Massachusetts"


def test_normalize_candidate_location_prefers_us_postal_segment_over_city_state_name() -> None:
    normalized = normalize_candidate_location(
        candidate(
            address_line1="406 W Patrick St, California, MO 65018",
            city=None,
            region="California",
            country="United States",
            occurrences=[occurrence("America/Chicago")],
        )
    )

    assert normalized.city == "California"
    assert normalized.region == "Missouri"


def test_normalize_candidate_location_ignores_state_name_in_numbered_street() -> None:
    normalized = normalize_candidate_location(
        candidate(
            address_line1="10017 E Kentucky Rd, Independence, MO 64053",
            city=None,
            region="Kentucky",
            country="United States",
            occurrences=[occurrence("America/Chicago")],
        )
    )

    assert normalized.city == "Independence"
    assert normalized.region == "Missouri"


def test_normalize_candidate_location_ignores_directional_state_abbrev_in_street() -> None:
    normalized = normalize_candidate_location(
        candidate(
            address_line1="Christ Lutheran Church, 15029 2nd St NE, Aurora, OR 97002",
            city="Christ Lutheran Church",
            region="Nebraska",
            country="United States",
            occurrences=[occurrence("America/Los_Angeles")],
        )
    )

    assert normalized.region == "Oregon"


def test_normalize_candidate_location_record_address_overrides_source_region() -> None:
    normalized = normalize_candidate_location(
        candidate(
            fellowship="na",
            source_id="na-remote",
            address_line1="Sarnia, Ontario",
            city=None,
            region="Mississippi",
            country="United States",
            occurrences=[occurrence("America/Chicago")],
        ),
        source(
            id="na-remote",
            fellowship="na",
            country="United States",
            region="Mississippi",
        ),
    )

    assert normalized.city == "Sarnia"
    assert normalized.region == "Ontario"
    assert normalized.country == "Canada"


def test_normalize_candidate_location_uses_source_region_when_scraped_region_is_city() -> None:
    normalized = normalize_candidate_location(
        candidate(
            source_id="aa-boston",
            address_line1="12 Channel St",
            city=None,
            region="Boston",
            country="United States",
            occurrences=[occurrence("America/New_York")],
        ),
        source(
            id="aa-boston",
            country="United States",
            region="Massachusetts",
        ),
    )

    assert normalized.region == "Massachusetts"


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


def test_build_snapshot_extracts_uk_country_and_postcode_parts() -> None:
    snapshot = build_snapshot(
        [
            candidate(
                address_line1="2 Windsor Rd, London W5 5PD, Wielka Brytania",
                country=None,
                occurrences=[occurrence("Europe/London")],
            )
        ]
    )

    meeting = snapshot.meetings[0]

    assert meeting.address_line1 == "2 Windsor Rd"
    assert meeting.city == "London"
    assert meeting.postal_code == "W5 5PD"
    assert meeting.country == "United Kingdom"
    assert meeting.country_code == "GB"


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


def test_location_audit_does_not_treat_us_state_zip_as_eircode() -> None:
    snapshot = build_snapshot(
        [
            candidate(
                address_line1="Wood Ave & N Victoria Rd, Texas 78537",
                region="Texas",
                country="United States",
                occurrences=[occurrence("America/Chicago")],
            )
        ]
    )

    audit = audit_snapshot_meetings(snapshot.meetings)

    assert audit.issue_counts["high_confidence_country_conflict"] == 0


def test_location_audit_does_not_treat_city_name_as_country_conflict() -> None:
    snapshot = build_snapshot(
        [
            candidate(
                address_line1="2 Strickland St, Denmark WA 6333",
                city="Denmark",
                region="WA",
                country="Australia",
                occurrences=[occurrence("Australia/Perth")],
            )
        ]
    )

    audit = audit_snapshot_meetings(snapshot.meetings)

    assert audit.issue_counts["high_confidence_country_conflict"] == 0


def test_normalize_candidate_location_prefers_trailing_country_over_city_segment() -> None:
    meeting = candidate(
        address_line1="5315 N Twin City Hwy, Nederland, TX 77627, USA",
        city="Nederland",
        region="Texas",
        country="Netherlands",
        occurrences=[occurrence("Europe/Amsterdam")],
    )
    normalized = normalize_candidate_location(meeting)
    audit = audit_snapshot_meetings(build_snapshot([meeting]).meetings)

    assert normalized.city == "Nederland"
    assert normalized.region == "Texas"
    assert normalized.country == "United States"
    assert normalized.occurrences[0].timezone == "America/Chicago"
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

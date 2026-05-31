from app.normalize.canonical import CanonicalMeetingCandidate
from app.normalize.dedupe import consolidate_duplicate_candidates, find_duplicate_candidates


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


def test_consolidate_duplicate_candidates_merges_na_portlaoise_occurrences() -> None:
    monday = _candidate(
        fellowship="na",
        source_id="na-2d0fad4641a8",
        source_record_id="257",
        name="Step To Freedom Group Portlaoise",
        address_line1="Knockmay, Portlaoise, R32 R624",
        country="Ireland",
        day_of_week=1,
        start_time_local="20:00",
    )
    saturday = _candidate(
        fellowship="na",
        source_id="na-565ff8e141b7",
        source_record_id="755",
        name="Step To Freedom Group Portlaoise",
        address_line1="Knockmay, Portlaoise",
        country="Ireland",
        day_of_week=6,
        start_time_local="19:00",
    )

    result = consolidate_duplicate_candidates([monday, saturday])

    assert result.metrics.original_count == 2
    assert result.metrics.consolidated_count == 1
    assert result.metrics.removed_by_fellowship == {"na": 1}
    assert [
        (occurrence.day_of_week, str(occurrence.start_time_local))
        for occurrence in result.candidates[0].occurrences
    ] == [(1, "20:00:00"), (6, "19:00:00")]


def test_consolidate_duplicate_candidates_merges_ca_oz_house_weekday_rows() -> None:
    rows = [
        _candidate(
            fellowship="ca",
            source_id="ca-23bc07bc85b3",
            source_record_id=str(day),
            name="C.A. Oz House",
            venue_name="Co. Galway" if day > 1 else "Ozanam House is closed on bank holidays.",
            address_line1="Room 3, St. Augustine Street",
            city="Not wheelchair accessible" if day > 1 else "",
            country="Ireland",
            day_of_week=day,
            start_time_local="15:00",
        )
        for day in range(1, 6)
    ]

    result = consolidate_duplicate_candidates(rows)

    assert result.metrics.consolidated_count == 1
    assert result.metrics.removed_by_fellowship == {"ca": 4}
    assert len(result.candidates[0].occurrences) == 5


def test_consolidate_duplicate_candidates_merges_aa_australia_source_overlap() -> None:
    nsw = _candidate(
        fellowship="aa",
        source_id="aa-08512eb5f89d",
        source_record_id="nsw-1",
        name="Bondi Beginners",
        address_line1="1 Beach Road",
        city="Bondi",
        region="NSW",
        country="Australia",
        day_of_week=2,
        start_time_local="18:30",
    )
    national = _candidate(
        fellowship="aa",
        source_id="aa-b60e7af83fb9",
        source_record_id="au-1",
        name="Bondi Beginners",
        address_line1="1 Beach Rd",
        city="Bondi",
        region="New South Wales",
        country="Australia",
        day_of_week=2,
        start_time_local="18:30",
    )

    result = consolidate_duplicate_candidates([national, nsw])

    assert result.metrics.consolidated_count == 1
    assert result.metrics.exact_occurrence_duplicate_groups_by_fellowship == {"aa": 1}
    assert result.candidates[0].source_id == "aa-08512eb5f89d"


def test_consolidate_duplicate_candidates_prefers_most_common_display_name() -> None:
    typo = _candidate(
        fellowship="na",
        source_id="na-2d0fad4641a8",
        source_record_id="314",
        name="DIngle Online and Physically Open",
        address_line1="off Green Street, Dingle",
        country="Ireland",
        day_of_week=5,
        start_time_local="20:30",
    )
    corrected = _candidate(
        fellowship="na",
        source_id="na-565ff8e141b7",
        source_record_id="893",
        name="Dingle Online and Physically Open",
        address_line1="off Green St, Dingle",
        country="Ireland",
        day_of_week=2,
        start_time_local="19:30",
    )
    duplicate_corrected = corrected.model_copy(
        update={"source_id": "na-e9c7fc6d1f46", "source_record_id": "5"}
    )

    result = consolidate_duplicate_candidates([typo, corrected, duplicate_corrected])

    assert result.candidates[0].name == "Dingle Online and Physically Open"


def _candidate(
    *,
    fellowship: str,
    source_id: str,
    source_record_id: str,
    name: str,
    address_line1: str,
    country: str,
    day_of_week: int,
    start_time_local: str,
    venue_name: str | None = None,
    city: str | None = None,
    region: str | None = None,
) -> CanonicalMeetingCandidate:
    return CanonicalMeetingCandidate(
        fellowship=fellowship,
        source_id=source_id,
        source_record_id=source_record_id,
        source_url="https://example.org/meetings",
        name=name,
        meeting_type="in_person",
        venue_name=venue_name,
        address_line1=address_line1,
        city=city,
        region=region,
        country=country,
        occurrences=[
            {
                "day_of_week": day_of_week,
                "start_time_local": start_time_local,
                "timezone": "Europe/Dublin" if country == "Ireland" else "Australia/Sydney",
            }
        ],
    )

from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence
from app.storage.repositories import _candidate_params, _import_run_from_row


def test_import_run_from_row_maps_counts() -> None:
    run = _import_run_from_row(
        {
            "id": "run-1",
            "source_id": "source-1",
            "status": "succeeded",
            "records_fetched": 10,
            "records_changed": 8,
            "review_flags_created": 2,
            "error_message": None,
        }
    )

    assert run.id == "run-1"
    assert run.status == "succeeded"
    assert run.records_fetched == 10
    assert run.records_changed == 8
    assert run.review_flags_created == 2


def test_candidate_params_serializes_urls_and_formats() -> None:
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id="aa-feed",
        source_record_id="online",
        source_url="https://example.org/meetings.json",
        name="Online Meeting",
        meeting_type="online",
        online_url="https://zoom.example.org/j/123",
        formats=["Online", "Open"],
        occurrences=[
            MeetingOccurrence(day_of_week=1, start_time_local="19:30", timezone="Europe/Dublin")
        ],
    )

    params = _candidate_params(candidate)

    assert params["online_url"] == "https://zoom.example.org/j/123"
    assert params["formats"] == ["Online", "Open"]
    assert params["source_record_id"] == "online"

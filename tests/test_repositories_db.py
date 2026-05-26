import os
from datetime import UTC, datetime

import pytest

from app.config import Settings
from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence
from app.review.flags import ReviewFlag
from app.sources.registry import (
    AdapterType,
    Source,
    SourceCandidate,
    SourceType,
    source_from_candidate,
)
from app.storage.db import connect
from app.storage.repositories import (
    CanonicalMeetingRepository,
    ImportRunRepository,
    ReviewFlagRepository,
    SnapshotRepository,
    SourceRepository,
)

pytestmark = pytest.mark.db


def test_source_repository_upsert_and_lookup_requires_local_db() -> None:
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("set RUN_DB_TESTS=1 to run local Postgres integration tests")

    settings = Settings()
    candidate = SourceCandidate(
        fellowship="aa",
        label="Integration Test Source",
        url="https://integration.example.org/meetings",
        country="US",
    )
    source = source_from_candidate(candidate)

    with connect(settings) as connection:
        repository = SourceRepository(connection)
        stored = repository.upsert_source(source)
        loaded = repository.get_source(stored.id)
        connection.rollback()

    assert loaded is not None
    assert loaded.id == stored.id
    assert loaded.normalized_url == "https://integration.example.org/meetings"


def test_discovery_upsert_preserves_configured_adapter_requires_local_db() -> None:
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("set RUN_DB_TESTS=1 to run local Postgres integration tests")

    settings = Settings()
    configured = Source(
        id="integration-configured-aa",
        fellowship="aa",
        name="Configured AA Source",
        url="https://integration.example.org/configured-aa",
        normalized_url="https://integration.example.org/configured-aa",
        country="US",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
        requires_browser=True,
        config={"scrape": {"artifact_import": True}},
    )
    discovered = source_from_candidate(
        SourceCandidate(
            fellowship="aa",
            label="Configured AA Source Rediscovered",
            url="https://integration.example.org/configured-aa",
            country="US",
        )
    )

    with connect(settings) as connection:
        repository = SourceRepository(connection)
        repository.upsert_source(configured)
        stored = repository.upsert_source(discovered)
        connection.rollback()

    assert stored.adapter_type == AdapterType.PLAYWRIGHT_BROWSER
    assert stored.requires_browser is True
    assert stored.config["scrape"]["artifact_import"] is True


def test_feed_reclassification_clears_browser_requirement_requires_local_db() -> None:
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("set RUN_DB_TESTS=1 to run local Postgres integration tests")

    settings = Settings()
    browser_source = Source(
        id="integration-na-browser",
        fellowship="na",
        name="NA Browser Source",
        url="https://integration.example.org/na-browser",
        normalized_url="https://integration.example.org/na-browser",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
        requires_browser=True,
    )
    feed_source = browser_source.model_copy(
        update={
            "source_type": SourceType.MEETING_FEED,
            "adapter_type": AdapterType.BMLT,
            "requires_browser": False,
            "config": {"bmlt_search_endpoint": "https://integration.example.org/bmlt"},
        }
    )

    with connect(settings) as connection:
        repository = SourceRepository(connection)
        repository.upsert_source(browser_source)
        stored = repository.upsert_source(feed_source)
        connection.rollback()

    assert stored.adapter_type == AdapterType.BMLT
    assert stored.source_type == SourceType.MEETING_FEED
    assert stored.requires_browser is False


def test_import_run_repository_requires_local_db() -> None:
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("set RUN_DB_TESTS=1 to run local Postgres integration tests")

    settings = Settings()
    candidate = SourceCandidate(
        fellowship="aa",
        label="Integration Test Import Source",
        url="https://integration.example.org/import-meetings",
        country="US",
    )
    source = source_from_candidate(candidate)

    with connect(settings) as connection:
        source_repository = SourceRepository(connection)
        stored_source = source_repository.upsert_source(source)
        run_repository = ImportRunRepository(connection)
        run = run_repository.start(stored_source.id)
        finished = run_repository.finish(
            run.id,
            status="succeeded",
            records_fetched=3,
            records_changed=2,
            review_flags_created=1,
        )
        connection.rollback()

    assert finished.status == "succeeded"
    assert finished.records_fetched == 3
    assert finished.records_changed == 2
    assert finished.review_flags_created == 1


def test_canonical_meeting_repository_upsert_is_idempotent_requires_local_db() -> None:
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("set RUN_DB_TESTS=1 to run local Postgres integration tests")

    settings = Settings()
    source = source_from_candidate(
        SourceCandidate(
            fellowship="aa",
            label="Integration Test Canonical Source",
            url="https://integration.example.org/canonical-meetings",
            country="US",
        )
    )
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id=source.id,
        source_record_id="canonical-1",
        source_url=source.url,
        name="Canonical Test Meeting",
        meeting_type="in_person",
        venue_name="Test Hall",
        address_line1="1 Test Street",
        city="Testville",
        country="US",
        occurrences=[
            MeetingOccurrence(day_of_week=2, start_time_local="18:00", timezone="America/New_York")
        ],
    )

    with connect(settings) as connection:
        SourceRepository(connection).upsert_source(source)
        repository = CanonicalMeetingRepository(connection)
        repository.upsert_candidates([candidate])
        repository.upsert_candidates([candidate])
        meeting_count = repository.count_meetings()
        occurrence_count = repository.count_occurrences()
        connection.rollback()

    assert meeting_count >= 1
    assert occurrence_count >= 1


def test_review_flags_are_persisted_and_error_flags_block_snapshot_requires_local_db() -> None:
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("set RUN_DB_TESTS=1 to run local Postgres integration tests")

    settings = Settings()
    source = source_from_candidate(
        SourceCandidate(
            fellowship="aa",
            label="Integration Test Review Source",
            url="https://integration.example.org/review-meetings",
            country="US",
        )
    )
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id=source.id,
        source_record_id="review-1",
        source_url=source.url,
        name="Review Test Meeting",
        meeting_type="in_person",
        venue_name="Test Hall",
        address_line1="1 Test Street",
        city="Testville",
        country="US",
        occurrences=[
            MeetingOccurrence(day_of_week=2, start_time_local="18:00", timezone="America/New_York")
        ],
    )

    with connect(settings) as connection:
        SourceRepository(connection).upsert_source(source)
        canonical_repository = CanonicalMeetingRepository(connection)
        canonical_repository.upsert_candidates([candidate])
        review_repository = ReviewFlagRepository(connection)
        warning_count = review_repository.replace_flags_for_source(
            source.id,
            [],
        )
        candidates_without_error = canonical_repository.list_active_candidates_for_snapshot()
        error_count = review_repository.replace_flags_for_source(
            source.id,
            [
                ReviewFlag(
                    code="source_large_drop",
                    severity="error",
                    message="large drop",
                    source_record_id="review-1",
                )
            ],
        )
        candidates_with_error = canonical_repository.list_active_candidates_for_snapshot()
        connection.rollback()

    assert warning_count == 0
    assert any(item.source_record_id == "review-1" for item in candidates_without_error)
    assert error_count == 1
    assert all(item.source_record_id != "review-1" for item in candidates_with_error)


def test_snapshot_excludes_source_marked_excluded_requires_local_db() -> None:
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("set RUN_DB_TESTS=1 to run local Postgres integration tests")

    settings = Settings()
    source = source_from_candidate(
        SourceCandidate(
            fellowship="aa",
            label="Integration Test Excluded Source",
            url="https://integration.example.org/excluded-meetings",
            country="US",
        )
    ).model_copy(update={"config": {"snapshot_excluded": True}})
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id=source.id,
        source_record_id="excluded-1",
        source_url=source.url,
        name="Excluded Test Meeting",
        meeting_type="in_person",
        venue_name="Test Hall",
        address_line1="1 Test Street",
        city="Testville",
        country="US",
        occurrences=[
            MeetingOccurrence(day_of_week=2, start_time_local="18:00", timezone="America/New_York")
        ],
    )

    with connect(settings) as connection:
        SourceRepository(connection).upsert_source(source)
        canonical_repository = CanonicalMeetingRepository(connection)
        canonical_repository.upsert_candidates([candidate])
        candidates = canonical_repository.list_active_candidates_for_snapshot()
        connection.rollback()

    assert all(item.source_record_id != "excluded-1" for item in candidates)


def test_missing_meetings_become_stale_then_inactive_requires_local_db() -> None:
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("set RUN_DB_TESTS=1 to run local Postgres integration tests")

    settings = Settings()
    source = source_from_candidate(
        SourceCandidate(
            fellowship="aa",
            label="Integration Test Stale Source",
            url="https://integration.example.org/stale-meetings",
            country="US",
        )
    )
    candidate = CanonicalMeetingCandidate(
        fellowship="aa",
        source_id=source.id,
        source_record_id="stale-1",
        source_url=source.url,
        name="Stale Test Meeting",
        meeting_type="in_person",
        venue_name="Test Hall",
        address_line1="1 Test Street",
        city="Testville",
        country="US",
    )

    with connect(settings) as connection:
        SourceRepository(connection).upsert_source(source)
        repository = CanonicalMeetingRepository(connection)
        repository.upsert_candidates([candidate])
        first = repository.mark_missing_for_source(source.id, set())
        second = repository.mark_missing_for_source(source.id, set())
        third = repository.mark_missing_for_source(source.id, set())
        connection.rollback()

    assert first == 1
    assert second == 1
    assert third == 1


def test_snapshot_repository_records_export_requires_local_db() -> None:
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("set RUN_DB_TESTS=1 to run local Postgres integration tests")

    settings = Settings()
    with connect(settings) as connection:
        snapshot_id = SnapshotRepository(connection).record_snapshot(
            schema_version="test",
            path="/tmp/test-snapshot.json",
            meeting_count=2,
            blocked_by_review_count=1,
            generated_at=datetime.now(UTC),
        )
        connection.rollback()

    assert snapshot_id

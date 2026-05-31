import asyncio
import json
from types import SimpleNamespace

from typer.testing import CliRunner

from app.cli import (
    _ca_world_listings_shadowed_by_local_sources,
    _filter_sources_by_ids,
    _filter_sources_for_scrape_retry,
    _is_scrapeable_source,
    _persist_ingest_result,
    _scrape_source,
    _scrape_sources,
    _select_scrape_batch,
    _source_for_scrape_all,
    _source_last_scrape_failed,
    _source_with_scrape_metadata,
    _source_with_scrape_status,
    _timezone_for_cleanup_row,
    app,
)
from app.config import Settings
from app.ingest import IngestResult
from app.normalize.canonical import CanonicalMeetingCandidate, MeetingOccurrence
from app.scraping.models import CrawlSettings, ExtractedMeeting, ScrapedPage, ScrapeSourceResult
from app.scraping.service import ScrapeResult
from app.sources.registry import AdapterType, Source, SourceType

from .conftest import FIXTURES


def test_discover_sources_dry_run_uses_fixture() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "discover-sources",
            "--fellowship",
            "aa",
            "--fixture",
            str(FIXTURES / "aa_world.html"),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "fellowship: aa" in result.output
    assert "candidates: 4" in result.output
    assert "not written because --dry-run was set" in result.output


def test_ingest_source_dry_run_uses_meeting_guide_fixture() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "ingest-source",
            "--source-id",
            "aa-ie-feed",
            "--fixture",
            str(FIXTURES / "meeting_guide.json"),
            "--adapter",
            "meeting_guide",
            "--fellowship",
            "aa",
            "--source-url",
            "https://example.org/meetings.json",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "records_fetched: 2" in result.output
    assert "candidates_normalized: 2" in result.output
    assert "not written because --dry-run was set" in result.output


def test_ingest_source_dry_run_uses_bmlt_fixture() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "ingest-source",
            "--source-id",
            "na-ie-bmlt",
            "--fixture",
            str(FIXTURES / "bmlt.json"),
            "--adapter",
            "bmlt",
            "--fellowship",
            "na",
            "--source-url",
            "https://bmlt.example.org/main_server",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "records_fetched: 1" in result.output
    assert "candidates_normalized: 1" in result.output


def test_scrape_source_dry_run_uses_html_fixture(tmp_path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "scrape-source",
            "--source-id",
            "aa-browser",
            "--fixture",
            str(FIXTURES / "static_meetings.html"),
            "--source-url",
            "https://example.org/meetings",
            "--output-dir",
            str(tmp_path / "artifacts"),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "scrape_status: succeeded" in result.output
    assert "pages_visited: 1" in result.output
    assert "records_extracted: 1" in result.output
    assert "candidates_normalized: 1" in result.output
    assert "artifact_dir:" in result.output


def test_ca_world_listing_is_shadowed_when_local_source_exists() -> None:
    sources = [
        Source(
            id="ca-world-thailand",
            fellowship="ca",
            name="Thailand",
            url="https://ca.org/meetings/thailand/",
            source_type=SourceType.WORLD_SERVICE_LISTING,
        ),
        Source(
            id="ca-thailand",
            fellowship="ca",
            name="Thailand Area",
            url="https://cathailand.org",
            source_type=SourceType.LOCAL_SERVICE_BODY,
            config={"metadata": {"world_source": "https://ca.org/meetings/thailand/"}},
        ),
    ]

    assert _ca_world_listings_shadowed_by_local_sources(sources) == {"ca-world-thailand"}


def test_select_scrape_batch_applies_offset_before_limit() -> None:
    sources = [
        Source(
            id=f"aa-{index}",
            fellowship="aa",
            name=f"Source {index}",
            url=f"https://example.org/{index}",
        )
        for index in range(5)
    ]

    selected = _select_scrape_batch(sources, offset=2, limit=2)

    assert [source.id for source in selected] == ["aa-2", "aa-3"]


def test_filter_sources_by_ids_preserves_source_order() -> None:
    sources = [
        Source(
            id=f"aa-{index}",
            fellowship="aa",
            name=f"Source {index}",
            url=f"https://example.org/{index}",
        )
        for index in range(4)
    ]

    selected = _filter_sources_by_ids(sources, ["aa-3", "aa-1"])

    assert [source.id for source in selected] == ["aa-1", "aa-3"]


def test_scrape_all_preserves_direct_feed_sources() -> None:
    source = Source(
        id="na-bmlt",
        fellowship="na",
        name="NA BMLT",
        url="https://example.org/main_server",
        source_type=SourceType.MEETING_FEED,
        adapter_type=AdapterType.BMLT,
    )

    selected = _source_for_scrape_all(source)

    assert selected.adapter_type == AdapterType.BMLT
    assert selected.source_type == SourceType.MEETING_FEED
    assert not selected.requires_browser


def test_scrapeable_source_skips_classified_unknown_by_default() -> None:
    source = Source(
        id="na-unknown",
        fellowship="na",
        name="NA Unknown",
        url="https://example.org",
        adapter_type=AdapterType.UNKNOWN,
        config={"classification": {"reason": "no meeting page or feed found"}},
    )

    assert not _is_scrapeable_source(source)
    assert _is_scrapeable_source(source, include_classified_unknown=True)


def test_filter_sources_for_scrape_retry_selects_failed_and_zero_record_sources() -> None:
    failed = Source(
        id="na-failed",
        fellowship="na",
        name="Failed",
        url="https://example.org/failed",
        config={"scrape": {"last_status": "failed", "last_records_extracted": 0}},
    )
    zero = Source(
        id="na-zero",
        fellowship="na",
        name="Zero",
        url="https://example.org/zero",
        config={"scrape": {"last_status": "succeeded", "last_records_extracted": 0}},
    )
    useful = Source(
        id="na-useful",
        fellowship="na",
        name="Useful",
        url="https://example.org/useful",
        config={"scrape": {"last_status": "succeeded", "last_records_extracted": 4}},
    )
    feed = Source(
        id="na-feed",
        fellowship="na",
        name="Feed",
        url="https://example.org/main_server",
        source_type=SourceType.MEETING_FEED,
        adapter_type=AdapterType.BMLT,
        config={"scrape": {"last_status": "succeeded", "last_records_extracted": 0}},
    )

    selected = _filter_sources_for_scrape_retry(
        [failed, zero, useful, feed],
        only_failed=True,
        only_zero_records=True,
    )

    assert [source.id for source in selected] == ["na-failed", "na-zero"]


def test_timezone_cleanup_prefers_source_region_for_missing_timezone() -> None:
    row = {
        "meeting_country": None,
        "meeting_region": None,
        "source_country": "United States",
        "source_region": "Minnesota",
        "source_name": "Minnesota Region",
        "source_url": "https://example.org",
        "source_config": {},
    }

    assert _timezone_for_cleanup_row(row) == "America/Chicago"


def test_timezone_cleanup_leaves_broad_multi_timezone_country_ambiguous() -> None:
    row = {
        "meeting_country": "Russian Federation",
        "meeting_region": None,
        "source_country": "Russian Federation",
        "source_region": None,
        "source_name": "Russia Region",
        "source_url": "https://example.org",
        "source_config": {},
    }

    assert _timezone_for_cleanup_row(row) is None


def test_timezone_cleanup_uses_specific_source_text_hint() -> None:
    row = {
        "meeting_country": "Russian Federation",
        "meeting_region": None,
        "source_country": "Russian Federation",
        "source_region": None,
        "source_name": "Ural & W Siberia Region",
        "source_url": "https://example.org",
        "source_config": {},
    }

    assert _timezone_for_cleanup_row(row) == "Asia/Yekaterinburg"


def test_timezone_cleanup_uses_single_timezone_country() -> None:
    row = {
        "meeting_country": None,
        "meeting_region": None,
        "source_country": "India",
        "source_region": None,
        "source_name": "Delhi Area",
        "source_url": "https://example.org",
        "source_config": {},
    }

    assert _timezone_for_cleanup_row(row) == "Asia/Kolkata"


async def test_scrape_source_directly_ingests_feed_adapter(monkeypatch) -> None:
    source = Source(
        id="na-bmlt",
        fellowship="na",
        name="NA BMLT",
        url="https://example.org/main_server",
        source_type=SourceType.MEETING_FEED,
        adapter_type=AdapterType.BMLT,
    )
    calls: list[str] = []

    async def fake_ingest_source(source_arg, settings_arg, fixture=None):
        calls.append(source_arg.id)
        assert isinstance(settings_arg, Settings)
        assert fixture is None
        return IngestResult(raw_records=[], candidates=[], review_flags=[])

    async def unexpected_scrape_source(*args, **kwargs):
        raise AssertionError("direct feed adapters should not launch browser scraping")

    monkeypatch.setattr("app.cli.run_ingest_source", fake_ingest_source)
    monkeypatch.setattr("app.cli.run_scrape_source", unexpected_scrape_source)

    result = await _scrape_source(
        source,
        Settings(),
        fixture=None,
        crawl_settings=CrawlSettings(),
        output_dir=None,
    )

    assert calls == ["na-bmlt"]
    assert result.scrape.status == "succeeded"
    assert result.scrape.pages_visited == 0


async def test_scrape_sources_respects_concurrency(monkeypatch, tmp_path) -> None:
    active = 0
    max_seen = 0

    async def fake_scrape_source(
        source,
        settings,
        *,
        fixture,
        crawl_settings,
        output_dir,
    ):
        nonlocal active, max_seen
        assert fixture is None
        assert isinstance(settings, Settings)
        assert isinstance(crawl_settings, CrawlSettings)
        assert output_dir == tmp_path
        active += 1
        max_seen = max(max_seen, active)
        await asyncio.sleep(0.01)
        active -= 1
        return ScrapeResult(
            scrape=ScrapeSourceResult(
                source_id=source.id,
                source_url=source.url,
                status="succeeded",
            ),
            ingest=IngestResult(raw_records=[], candidates=[], review_flags=[]),
        )

    monkeypatch.setattr("app.cli._scrape_source", fake_scrape_source)
    sources = [
        Source(
            id=f"aa-{index}",
            fellowship="aa",
            name=f"Source {index}",
            url=f"https://example.org/{index}",
        )
        for index in range(4)
    ]

    await _scrape_sources(
        sources,
        Settings(),
        dry_run=True,
        crawl_settings=CrawlSettings(),
        output_dir=tmp_path,
        concurrency=2,
    )

    assert max_seen == 2


def test_export_snapshot_db_failure_does_not_write_empty_snapshot(monkeypatch, tmp_path) -> None:
    def broken_connect(settings):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.cli.connect", broken_connect)
    monkeypatch.setattr(
        "app.cli.get_settings",
        lambda: Settings(snapshot_output_dir=tmp_path),
    )

    result = CliRunner().invoke(app, ["export-snapshot", "--no-dry-run"])

    assert result.exit_code != 0
    assert not (tmp_path / "latest.json").exists()


def test_export_snapshot_dry_run_prints_duplicate_metrics(monkeypatch, tmp_path) -> None:
    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeCanonicalRepository:
        def __init__(self, connection):
            self.connection = connection

        def list_active_candidates_for_snapshot(self):
            return [
                CanonicalMeetingCandidate(
                    fellowship="ca",
                    source_id="ca-23bc07bc85b3",
                    source_record_id="monday",
                    source_url="https://www.caireland.live/meeting-schedule",
                    name="C.A. Oz House",
                    meeting_type="in_person",
                    address_line1="Room 3, St. Augustine Street",
                    country="Ireland",
                    occurrences=[
                        MeetingOccurrence(
                            day_of_week=1,
                            start_time_local="15:00",
                            timezone="Europe/Dublin",
                        )
                    ],
                ),
                CanonicalMeetingCandidate(
                    fellowship="ca",
                    source_id="ca-23bc07bc85b3",
                    source_record_id="tuesday",
                    source_url="https://www.caireland.live/meeting-schedule",
                    name="C.A. Oz House",
                    meeting_type="in_person",
                    address_line1="Room 3, St Augustine Street",
                    city="Not wheelchair accessible",
                    country="Ireland",
                    occurrences=[
                        MeetingOccurrence(
                            day_of_week=2,
                            start_time_local="15:00",
                            timezone="Europe/Dublin",
                        )
                    ],
                ),
            ]

    class FakeReviewRepository:
        def __init__(self, connection):
            self.connection = connection

        def count_open_error_flags(self):
            return 0

    monkeypatch.setattr("app.cli.connect", lambda settings: FakeConnection())
    monkeypatch.setattr("app.cli.CanonicalMeetingRepository", FakeCanonicalRepository)
    monkeypatch.setattr("app.cli.ReviewFlagRepository", FakeReviewRepository)
    monkeypatch.setattr(
        "app.cli.get_settings",
        lambda: Settings(snapshot_output_dir=tmp_path),
    )

    result = CliRunner().invoke(app, ["export-snapshot"])

    assert result.exit_code == 0
    assert "source_meetings: 2" in result.output
    assert "active_meetings: 1" in result.output
    assert "removed_count: 1" in result.output
    assert not (tmp_path / "latest.json").exists()


def test_persist_failed_scrape_does_not_replace_meetings_or_flags(monkeypatch) -> None:
    events: list[tuple[str, object]] = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def commit(self) -> None:
            events.append(("commit", None))

    class FakeSourceRepository:
        def __init__(self, connection):
            self.connection = connection

        def upsert_source(self, source):
            events.append(("source_status", source.config["scrape"]["last_status"]))
            return source

    class FakeImportRunRepository:
        def __init__(self, connection):
            self.connection = connection

        def start(self, source_id):
            events.append(("start", source_id))
            return SimpleNamespace(id="run-1")

        def finish(
            self,
            run_id,
            *,
            status,
            records_fetched,
            records_changed,
            review_flags_created,
            error_message=None,
        ):
            events.append(
                (
                    "finish",
                    status,
                    records_fetched,
                    records_changed,
                    review_flags_created,
                    error_message,
                )
            )
            return SimpleNamespace(id=run_id)

    class UnexpectedRepository:
        def __init__(self, connection):
            raise AssertionError("failed scrapes must not replace meeting data")

    monkeypatch.setattr("app.cli.connect", lambda settings: FakeConnection())
    monkeypatch.setattr("app.cli.SourceRepository", FakeSourceRepository)
    monkeypatch.setattr("app.cli.ImportRunRepository", FakeImportRunRepository)
    monkeypatch.setattr("app.cli.RawMeetingRepository", UnexpectedRepository)
    monkeypatch.setattr("app.cli.CanonicalMeetingRepository", UnexpectedRepository)
    monkeypatch.setattr("app.cli.ReviewFlagRepository", UnexpectedRepository)

    source = Source(
        id="aa-failed",
        fellowship="aa",
        name="Failed AA",
        url="https://example.org",
    )
    scrape = ScrapeSourceResult(
        source_id=source.id,
        source_url=source.url,
        status="failed",
        error_message="net::ERR_NAME_NOT_RESOLVED",
    )

    result = _persist_ingest_result(
        Settings(),
        source,
        IngestResult(raw_records=[], candidates=[], review_flags=[]),
        scrape=scrape,
    )

    assert result == {
        "raw_records_stored": 0,
        "canonical_meetings_upserted": 0,
        "meetings_marked_missing": 0,
        "review_flags_created": 0,
        "import_run_id": "run-1",
    }
    assert events == [
        ("source_status", "failed"),
        ("start", "aa-failed"),
        ("finish", "failed", 0, 0, 0, "net::ERR_NAME_NOT_RESOLVED"),
        ("commit", None),
    ]


def test_source_with_scrape_metadata_marks_failed_source_for_retry_skip() -> None:
    source = Source(
        id="aa-failed",
        fellowship="aa",
        name="Failed AA",
        url="https://example.org",
        config={"scrape": {"previous_adapter_type": "unknown"}},
    )
    scrape = ScrapeSourceResult(
        source_id=source.id,
        source_url=source.url,
        status="failed",
        error_message="net::ERR_NAME_NOT_RESOLVED at https://example.org",
    )

    updated = _source_with_scrape_metadata(source, scrape)

    assert _source_last_scrape_failed(updated)
    assert updated.config["scrape"]["previous_adapter_type"] == "unknown"
    assert updated.config["scrape"]["last_status"] == "failed"
    assert updated.config["scrape"]["last_pages_visited"] == 0
    assert updated.config["scrape"]["last_records_extracted"] == 0
    assert "ERR_NAME_NOT_RESOLVED" in updated.config["scrape"]["last_error"]


def test_source_with_scrape_metadata_clears_previous_error_after_success() -> None:
    source = Source(
        id="aa-succeeded",
        fellowship="aa",
        name="Succeeded AA",
        url="https://example.org",
        config={"scrape": {"last_status": "failed", "last_error": "timeout"}},
    )
    scrape = ScrapeSourceResult(
        source_id=source.id,
        source_url=source.url,
        status="succeeded",
        artifact_dir="scrape_artifacts/aa-succeeded",
    )

    updated = _source_with_scrape_metadata(source, scrape)

    assert not _source_last_scrape_failed(updated)
    assert updated.config["scrape"]["last_status"] == "succeeded"
    assert updated.config["scrape"]["last_artifact_dir"] == "scrape_artifacts/aa-succeeded"
    assert "last_error" not in updated.config["scrape"]


def test_source_with_scrape_metadata_remembers_successful_pages_by_record_count() -> None:
    source = Source(
        id="na-browser",
        fellowship="na",
        name="NA Browser",
        url="https://example.org",
    )
    scrape = ScrapeSourceResult(
        source_id=source.id,
        source_url=source.url,
        status="succeeded",
        pages=[
            ScrapedPage(
                url="https://example.org/",
                final_url="https://example.org/",
                title="Home",
                html="",
                extracted=[
                    ExtractedMeeting(
                        payload={"name": "Home Meeting"},
                        method="test",
                        confidence=0.9,
                        source_page_url="https://example.org/",
                    )
                ],
            ),
            ScrapedPage(
                url="https://example.org/find-a-meeting",
                final_url="https://example.org/find-a-meeting",
                title="Find a Meeting",
                html="",
                page_score=0.9,
                page_signals=["strong_public_meeting_directory"],
                extracted=[
                    ExtractedMeeting(
                        payload={"name": f"Meeting {index}"},
                        method="test",
                        confidence=0.9,
                        source_page_url="https://example.org/find-a-meeting",
                    )
                    for index in range(4)
                ],
            ),
        ],
    )

    updated = _source_with_scrape_metadata(source, scrape)

    scrape_config = updated.config["scrape"]
    assert scrape_config["last_successful_page_url"] == "https://example.org/find-a-meeting"
    assert scrape_config["last_successful_page_records"] == 4
    assert scrape_config["last_successful_page_signals"] == [
        "strong_public_meeting_directory"
    ]
    assert scrape_config["successful_pages"][0]["url"] == (
        "https://example.org/find-a-meeting"
    )


def test_source_with_scrape_status_uses_artifact_summary_counts() -> None:
    source = Source(
        id="aa-artifact",
        fellowship="aa",
        name="Artifact AA",
        url="https://example.org",
        config={"scrape": {"artifact_import": True}},
    )

    updated = _source_with_scrape_status(
        source,
        status="failed",
        pages_visited=3,
        records_extracted=0,
        artifact_dir="scrape_artifacts/aa-full/aa-artifact",
        error_message="certificate expired",
    )

    assert _source_last_scrape_failed(updated)
    assert updated.config["scrape"]["artifact_import"] is True
    assert updated.config["scrape"]["last_pages_visited"] == 3
    assert updated.config["scrape"]["last_records_extracted"] == 0
    assert updated.config["scrape"]["last_artifact_dir"].endswith("/aa-artifact")
    assert updated.config["scrape"]["last_error"] == "certificate expired"


def test_import_artifacts_dry_run_uses_summary_payload(tmp_path) -> None:
    artifact_root = tmp_path / "artifacts"
    source_dir = artifact_root / "aa-example"
    source_dir.mkdir(parents=True)
    (artifact_root / "controlled_smoke_report.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "aa-example",
                        "fellowship": "aa",
                        "name": "Example AA",
                        "url": "https://example.org/meetings",
                        "country": "IE",
                        "timezone": "Europe/Dublin",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (source_dir / "summary.json").write_text(
        json.dumps(
            {
                "source_id": "aa-example",
                "source_url": "https://example.org/meetings",
                "status": "succeeded",
                "pages_visited": 1,
                "records_extracted": 1,
                "pages": [
                    {
                        "url": "https://example.org/meetings",
                        "final_url": "https://example.org/meetings",
                        "title": "Meetings",
                        "extracted": [
                            {
                                "payload": {
                                    "name": "Monday Main",
                                    "day": "Monday",
                                    "time": "7:30 pm",
                                    "address_line1": "10 Main Street",
                                },
                                "method": "heuristic_table_row",
                                "confidence": 0.95,
                                "source_page_url": "https://example.org/meetings",
                                "signals": ["day", "time", "name"],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["import-artifacts", str(artifact_root), "--dry-run"])

    assert result.exit_code == 0
    assert "summaries: 1" in result.output
    assert "records_fetched: 1" in result.output
    assert "candidates_normalized: 1" in result.output
    assert "not written because --dry-run was set" in result.output

import json

from typer.testing import CliRunner

from app.cli import (
    _ca_world_listings_shadowed_by_local_sources,
    _select_scrape_batch,
    _source_last_scrape_failed,
    _source_with_scrape_metadata,
    _source_with_scrape_status,
    app,
)
from app.scraping.models import ExtractedMeeting, ScrapedPage, ScrapeSourceResult
from app.sources.registry import Source, SourceType

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

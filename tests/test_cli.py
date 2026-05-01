from typer.testing import CliRunner

from app.cli import app

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

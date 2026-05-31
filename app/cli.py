import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Protocol, runtime_checkable

import typer
from psycopg import Connection
from psycopg.rows import dict_row
from rich.console import Console

from app.config import Settings, get_settings
from app.export.snapshot import build_snapshot_with_quality
from app.export.snapshot import write_snapshot as write_snapshot_file
from app.ingest import IngestResult
from app.ingest import ingest_source as run_ingest_source
from app.logging import configure_logging
from app.normalize.canonical import CanonicalMeetingCandidate, Snapshot, SnapshotMeeting
from app.normalize.dedupe import DuplicateMetrics, consolidate_duplicate_candidates
from app.normalize.location_quality import audit_snapshot_meetings
from app.review.flags import flag_source_drop
from app.scraping.artifact_import import (
    import_artifact_summary,
    importable_artifact_summaries,
    source_metadata_by_id,
)
from app.scraping.evidence import write_scrape_evidence
from app.scraping.extract_meetings import extract_meetings_from_html
from app.scraping.models import CrawlSettings, ScrapedPage, ScrapeSourceResult
from app.scraping.service import ScrapeResult
from app.scraping.service import scrape_source as run_scrape_source
from app.scraping.zero_source_audit import audit_zero_sources, write_zero_source_audit
from app.sources.aa_world_services import AaWorldServicesDiscovery
from app.sources.ca_world_services import CaWorldServicesDiscovery, is_valid_ca_local_source_url
from app.sources.na_world_services import NaWorldServicesDiscovery
from app.sources.registry import (
    AdapterType,
    Source,
    SourceCandidate,
    SourceType,
    normalize_source_url,
    source_from_candidate,
    timezone_for_country_region,
    timezone_for_source_text,
)
from app.sources.site_classification import ClassificationResult, SourceProbeClassifier
from app.storage.db import connect
from app.storage.repositories import (
    CanonicalMeetingRepository,
    ImportRunRepository,
    RawMeetingRepository,
    ReviewFlagRepository,
    SnapshotRepository,
    SourceRepository,
)

app = typer.Typer(no_args_is_help=True)
console = Console()


class SourceDiscovery(Protocol):
    async def fetch_html(self) -> str:
        ...

    def parse_html(self, html: str) -> list[SourceCandidate]:
        ...


@runtime_checkable
class LiveSourceDiscovery(SourceDiscovery, Protocol):
    async def discover(self, max_locations: int | None = None) -> list[SourceCandidate]:
        ...


@app.callback()
def callback() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)


@app.command("discover-sources")
def discover_sources(
    fellowship: Annotated[str, typer.Option(help="Fellowship slug such as aa, ca, or na.")],
    dry_run: bool = True,
    fixture: Annotated[
        Path | None,
        typer.Option(help="Read saved HTML instead of fetching the live world-service page."),
    ] = None,
    url: Annotated[
        str | None,
        typer.Option(help="Override the default world-service discovery URL."),
    ] = None,
    max_locations: Annotated[
        int | None,
        typer.Option(
            help=(
                "Limit live recursive discovery for source pages or NA locator locations. "
                "Omit to scan every discovered location."
            ),
        ),
    ] = None,
) -> None:
    settings = get_settings()
    discovery = _discovery_for(fellowship, settings, url)
    candidates = asyncio.run(_discover_candidates(discovery, fixture, max_locations))
    sources = [source_from_candidate(candidate) for candidate in candidates]

    console.print(f"Source discovery dry_run={dry_run}")
    console.print(f"fellowship: {fellowship}")
    console.print(f"candidates: {len(sources)}")
    for source in sources[:10]:
        console.print(f"- {source.id} {source.name} {source.url}")
    if len(sources) > 10:
        console.print(f"... {len(sources) - 10} more")

    if dry_run:
        console.print("output: not written because --dry-run was set")
        return

    with connect(settings) as connection:
        repository = SourceRepository(connection)
        stored = [repository.upsert_source(source) for source in sources]
        connection.commit()
    console.print(f"stored_sources: {len(stored)}")


@app.command("clean-ca-sources")
def clean_ca_sources(
    dry_run: bool = True,
    include_with_meetings: Annotated[
        bool,
        typer.Option(help="Also delete invalid-looking CA sources that already have meetings."),
    ] = False,
) -> None:
    settings = get_settings()
    with connect(settings) as connection:
        repository = SourceRepository(connection)
        sources = repository.list_sources(fellowship="ca")
        invalid_sources = [
            source
            for source in sources
            if source.source_type == SourceType.LOCAL_SERVICE_BODY
            and not is_valid_ca_local_source_url(source.url)
        ]
        meeting_counts = _canonical_meeting_counts_by_source(connection, invalid_sources)
        protected_sources = [
            source
            for source in invalid_sources
            if meeting_counts.get(source.id, 0) > 0 and not include_with_meetings
        ]
        protected_source_ids = {source.id for source in protected_sources}
        deletable_sources = [
            source for source in invalid_sources if source.id not in protected_source_ids
        ]

        console.print(f"Clean CA sources dry_run={dry_run}")
        console.print(f"invalid_sources: {len(invalid_sources)}")
        console.print(f"protected_with_meetings: {len(protected_sources)}")
        console.print(f"deletable_sources: {len(deletable_sources)}")
        for source in deletable_sources[:20]:
            console.print(f"- {source.id} {source.name} {source.url}")
        if len(deletable_sources) > 20:
            console.print(f"... {len(deletable_sources) - 20} more")

        if dry_run:
            console.print("output: not written because --dry-run was set")
            return

        deleted = repository.delete_sources([source.id for source in deletable_sources])
        connection.commit()

    console.print(f"deleted_sources: {deleted}")


async def _discover_candidates(
    discovery: SourceDiscovery,
    fixture: Path | None,
    max_locations: int | None,
) -> list[SourceCandidate]:
    if fixture is not None:
        return discovery.parse_html(fixture.read_text(encoding="utf-8"))
    if isinstance(discovery, LiveSourceDiscovery):
        return await discovery.discover(max_locations=max_locations)
    html = await discovery.fetch_html()
    return discovery.parse_html(html)


def _canonical_meeting_counts_by_source(
    connection: Connection[Any],
    sources: list[Source],
) -> dict[str, int]:
    source_ids = [source.id for source in sources]
    if not source_ids:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT source_id, COUNT(*)
            FROM canonical_meetings
            WHERE source_id = ANY(%(source_ids)s)
            GROUP BY source_id
            """,
            {"source_ids": source_ids},
        )
        return {str(source_id): int(count) for source_id, count in cursor.fetchall()}


@app.command("ingest-source")
def ingest_source(
    source_id: Annotated[str, typer.Option(help="Source registry ID to ingest.")],
    dry_run: bool = True,
    fixture: Annotated[
        Path | None,
        typer.Option(help="Read saved JSON instead of fetching the live source."),
    ] = None,
    adapter: Annotated[
        AdapterType | None,
        typer.Option(help="Adapter to use when ingesting from a fixture without the DB."),
    ] = None,
    fellowship: Annotated[
        str,
        typer.Option(help="Fellowship slug for fixture ingestion."),
    ] = "aa",
    source_url: Annotated[
        str,
        typer.Option(help="Source URL for fixture ingestion."),
    ] = "https://example.org/meetings.json",
) -> None:
    console.print("deprecated: ingest-source is kept as a transition alias; prefer scrape-source")
    settings = get_settings()
    source = _source_for_ingest(source_id, settings, fixture, adapter, fellowship, source_url)
    result = asyncio.run(run_ingest_source(source, settings, fixture=fixture))
    console.print(f"Ingest source dry_run={dry_run}")
    console.print(f"source_id: {source_id}")
    console.print(f"adapter: {source.adapter_type}")
    console.print(f"records_fetched: {len(result.raw_records)}")
    console.print(f"candidates_normalized: {len(result.candidates)}")
    console.print(f"review_flags: {len(result.review_flags)}")
    if dry_run:
        console.print("output: not written because --dry-run was set")
        return

    persisted = _persist_ingest_result(settings, source, result)
    _print_persisted_result(persisted)


@app.command("ingest-all")
def ingest_all(dry_run: bool = True) -> None:
    console.print("deprecated: ingest-all is kept as a transition alias; prefer scrape-all")
    settings = get_settings()
    with connect(settings) as connection:
        sources = SourceRepository(connection).list_sources()
    console.print(f"Ingest all dry_run={dry_run}")
    console.print(f"sources: {len(sources)}")
    for source in sources:
        if not _is_ingestable_source(source):
            console.print(f"- {source.id} skipped: adapter={source.adapter_type}")
            continue
        try:
            result = asyncio.run(run_ingest_source(source, settings))
            console.print(
                f"- {source.id} adapter={source.adapter_type} "
                f"records={len(result.raw_records)} candidates={len(result.candidates)} "
                f"flags={len(result.review_flags)}"
            )
            if not dry_run:
                persisted = _persist_ingest_result(settings, source, result)
                console.print(
                    f"  stored={persisted['raw_records_stored']} "
                    f"canonical={persisted['canonical_meetings_upserted']} "
                    f"run={persisted['import_run_id']}"
                )
        except Exception as exc:
            console.print(f"- {source.id} failed: {exc}")


@app.command("scrape-source")
def scrape_source(
    source_id: Annotated[str, typer.Option(help="Source registry ID to scrape.")],
    dry_run: bool = True,
    fixture: Annotated[
        Path | None,
        typer.Option(help="Read saved rendered HTML instead of launching Playwright."),
    ] = None,
    adapter: Annotated[
        AdapterType,
        typer.Option(help="Adapter to use when scraping from a fixture without the DB."),
    ] = AdapterType.PLAYWRIGHT_BROWSER,
    fellowship: Annotated[
        str,
        typer.Option(help="Fellowship slug for fixture scraping."),
    ] = "aa",
    source_url: Annotated[
        str,
        typer.Option(help="Source URL for fixture scraping."),
    ] = "https://example.org/",
    max_pages: Annotated[int, typer.Option(help="Maximum pages to visit.")] = 20,
    max_depth: Annotated[int, typer.Option(help="Maximum link depth to crawl.")] = 2,
    save_artifacts: Annotated[
        bool,
        typer.Option(help="Write rendered HTML, JSON traces, and summaries."),
    ] = True,
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory for scrape artifacts."),
    ] = Path("scrape_artifacts"),
    headful: Annotated[
        bool,
        typer.Option(help="Run Chromium visibly instead of headless."),
    ] = False,
) -> None:
    settings = get_settings()
    source = _source_for_scrape(source_id, settings, fixture, adapter, fellowship, source_url)
    result = asyncio.run(
        _scrape_source(
            source,
            settings,
            fixture=fixture,
            crawl_settings=CrawlSettings(
                max_pages_per_source=max_pages,
                max_depth=max_depth,
                save_artifacts=save_artifacts,
                headless=not headful,
            ),
            output_dir=output_dir if save_artifacts else None,
        )
    )
    _print_scrape_result("Scrape source", dry_run, source, result)
    if dry_run:
        console.print("output: not written because --dry-run was set")
        return
    persisted = _persist_ingest_result(settings, source, result.ingest, scrape=result.scrape)
    _print_persisted_result(persisted)


@app.command("scrape-all")
def scrape_all(
    dry_run: bool = True,
    fellowship: Annotated[
        str | None,
        typer.Option(help="Only scrape sources for this fellowship."),
    ] = None,
    limit: Annotated[int | None, typer.Option(help="Maximum sources to scrape.")] = None,
    offset: Annotated[
        int,
        typer.Option(help="Number of scrapeable sources to skip before applying --limit."),
    ] = 0,
    max_pages_per_source: Annotated[
        int,
        typer.Option(help="Maximum pages to visit per source."),
    ] = 20,
    concurrency: Annotated[
        int,
        typer.Option(
            min=1,
            help="Maximum number of sources to scrape concurrently.",
        ),
    ] = 1,
    only_unknown: Annotated[
        bool,
        typer.Option(help="Only scrape sources without a configured ingest adapter."),
    ] = False,
    only_failed: Annotated[
        bool,
        typer.Option(help="Only scrape sources whose previous scrape status was failed."),
    ] = False,
    only_zero_records: Annotated[
        bool,
        typer.Option(
            help="Only scrape sources whose previous successful scrape found zero records.",
        ),
    ] = False,
    include_failed: Annotated[
        bool,
        typer.Option(help="Also retry sources with previous scrape failure metadata."),
    ] = False,
    include_classified_unknown: Annotated[
        bool,
        typer.Option(
            help="Also retry unknown sources that already have a classification reason.",
        ),
    ] = False,
    save_artifacts: Annotated[
        bool,
        typer.Option(help="Write scrape artifacts for each source."),
    ] = True,
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory for scrape artifacts."),
    ] = Path("scrape_artifacts"),
    source_ids: Annotated[
        list[str] | None,
        typer.Option(
            "--source-id",
            help="Only scrape this source ID. May be provided multiple times.",
        ),
    ] = None,
    headful: Annotated[
        bool,
        typer.Option(help="Run Chromium visibly instead of headless."),
    ] = False,
) -> None:
    settings = get_settings()
    with connect(settings) as connection:
        sources = SourceRepository(connection).list_sources(fellowship=fellowship)
    sources = _filter_sources_by_ids(sources, source_ids)
    if only_unknown:
        sources = [source for source in sources if source.adapter_type == AdapterType.UNKNOWN]
    sources = _filter_sources_for_scrape_retry(
        sources,
        only_failed=only_failed,
        only_zero_records=only_zero_records,
    )
    if not include_failed and not only_failed:
        sources = [source for source in sources if not _source_last_scrape_failed(source)]
    shadowed_world_listing_ids = _ca_world_listings_shadowed_by_local_sources(sources)
    scrapeable = [
        _source_for_scrape_all(source)
        for source in sources
        if _is_scrapeable_source(
            source,
            include_classified_unknown=include_classified_unknown,
        )
        and source.id not in shadowed_world_listing_ids
    ]
    scrapeable = _select_scrape_batch(scrapeable, offset=offset, limit=limit)

    console.print(f"Scrape all dry_run={dry_run}")
    console.print(f"sources: {len(scrapeable)}")
    if shadowed_world_listing_ids:
        console.print(
            "skipped_world_service_listings_with_local_sources: "
            f"{len(shadowed_world_listing_ids)}"
        )
    crawl_settings = CrawlSettings(
        max_pages_per_source=max_pages_per_source,
        save_artifacts=save_artifacts,
        headless=not headful,
    )
    asyncio.run(
        _scrape_sources(
            scrapeable,
            settings,
            dry_run=dry_run,
            crawl_settings=crawl_settings,
            output_dir=output_dir if save_artifacts else None,
            concurrency=concurrency,
        )
    )


@app.command("audit-zero-sources")
def audit_zero_sources_command(
    fellowship: Annotated[
        str,
        typer.Option(help="Only audit zero-active browser sources for this fellowship."),
    ] = "na",
    limit: Annotated[int | None, typer.Option(help="Maximum sources to audit.")] = None,
    offset: Annotated[
        int,
        typer.Option(help="Number of zero-active sources to skip before applying --limit."),
    ] = 0,
    concurrency: Annotated[
        int,
        typer.Option(min=1, help="Maximum number of live probes to run concurrently."),
    ] = 16,
    artifact_root: Annotated[
        Path,
        typer.Option(help="Root directory containing scrape artifact runs."),
    ] = Path("scrape_artifacts"),
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory to write the audit files."),
    ] = Path("scrape_artifacts/zero-source-audit"),
    live_probe: Annotated[
        bool,
        typer.Option(help="Fetch source URLs when saved artifacts are missing or failed."),
    ] = True,
    retry_concurrency: Annotated[
        int,
        typer.Option(help="Concurrency value included in the generated retry command."),
    ] = 8,
    retry_max_pages: Annotated[
        int,
        typer.Option(help="Max pages value included in the generated retry command."),
    ] = 8,
) -> None:
    settings = get_settings()
    with connect(settings) as connection:
        sources = _zero_active_browser_sources(connection, fellowship)
    sources = _select_scrape_batch(sources, offset=offset, limit=limit)

    console.print(f"Zero-source audit fellowship={fellowship}")
    console.print(f"sources: {len(sources)}")
    result = asyncio.run(
        audit_zero_sources(
            sources,
            artifact_root=artifact_root,
            concurrency=concurrency,
            live_probe=live_probe,
        )
    )
    retry_command = _zero_source_retry_command(
        result.retry_source_ids,
        fellowship=fellowship,
        concurrency=retry_concurrency,
        max_pages_per_source=retry_max_pages,
    )
    write_zero_source_audit(
        result,
        output_dir,
        fellowship=fellowship,
        retry_command=retry_command,
    )
    console.print(f"output_dir: {output_dir}")
    console.print(f"curated_retry_sources: {len(result.retry_source_ids)}")
    for bucket, count in result.bucket_counts.most_common():
        console.print(f"- {bucket}: {count}")


@app.command("debug-scrape-source")
def debug_scrape_source(
    source_id: Annotated[str, typer.Option(help="Source registry ID to debug scrape.")],
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory for debug scrape artifacts."),
    ] = Path("scrape_artifacts/debug"),
    fixture: Annotated[
        Path | None,
        typer.Option(help="Read saved rendered HTML instead of launching Playwright."),
    ] = None,
    adapter: Annotated[
        AdapterType,
        typer.Option(help="Adapter to use when debugging from a fixture without the DB."),
    ] = AdapterType.PLAYWRIGHT_BROWSER,
    fellowship: Annotated[str, typer.Option(help="Fellowship slug for fixture scraping.")] = "aa",
    source_url: Annotated[str, typer.Option(help="Source URL for fixture scraping.")] = (
        "https://example.org/"
    ),
    max_pages: Annotated[int, typer.Option(help="Maximum pages to visit.")] = 20,
    max_depth: Annotated[int, typer.Option(help="Maximum link depth to crawl.")] = 2,
    headful: Annotated[
        bool,
        typer.Option(help="Run Chromium visibly instead of headless."),
    ] = False,
) -> None:
    settings = get_settings()
    source = _source_for_scrape(source_id, settings, fixture, adapter, fellowship, source_url)
    result = asyncio.run(
        _scrape_source(
            source,
            settings,
            fixture=fixture,
            crawl_settings=CrawlSettings(
                max_pages_per_source=max_pages,
                max_depth=max_depth,
                save_artifacts=True,
                headless=not headful,
            ),
            output_dir=output_dir,
        )
    )
    _print_scrape_result("Debug scrape source", True, source, result)


@app.command("import-artifacts")
def import_artifacts(
    artifact_dir: Annotated[
        Path,
        typer.Argument(help="Scrape artifact run directory or one source summary.json file."),
    ],
    dry_run: bool = True,
    source_id: Annotated[
        str | None,
        typer.Option(help="Only import one source ID from the artifact run."),
    ] = None,
    include_failed: Annotated[
        bool,
        typer.Option(help="Also process summaries whose scrape status is failed."),
    ] = False,
) -> None:
    settings = get_settings()
    summaries = importable_artifact_summaries(
        artifact_dir,
        source_id=source_id,
        include_failed=include_failed,
    )
    metadata = _artifact_source_metadata_by_id(
        settings,
        artifact_dir if artifact_dir.is_dir() else artifact_dir.parent,
    )
    console.print(f"Import artifacts dry_run={dry_run}")
    console.print(f"artifact_dir: {artifact_dir}")
    console.print(f"summaries: {len(summaries)}")
    totals = {
        "records_extracted": 0,
        "records_fetched": 0,
        "candidates_normalized": 0,
        "review_flags": 0,
        "raw_records_stored": 0,
        "canonical_meetings_upserted": 0,
    }
    for summary_path in summaries:
        result = import_artifact_summary(
            summary_path,
            settings,
            source_metadata=metadata.get(summary_path.parent.name),
        )
        totals["records_extracted"] += result.records_extracted
        totals["records_fetched"] += len(result.ingest.raw_records)
        totals["candidates_normalized"] += len(result.ingest.candidates)
        totals["review_flags"] += len(result.ingest.review_flags)
        console.print(
            f"- {result.source.id} status={result.scrape_status} pages={result.pages_visited} "
            f"records={len(result.ingest.raw_records)} "
            f"candidates={len(result.ingest.candidates)} "
            f"flags={len(result.ingest.review_flags)}"
        )
        if result.error_message:
            console.print(f"  error={result.error_message}")
        if dry_run:
            continue
        persisted = _persist_ingest_result(
            settings,
            result.source,
            result.ingest,
            scrape_status=result.scrape_status,
            scrape_pages_visited=result.pages_visited,
            scrape_records_extracted=result.records_extracted,
            scrape_artifact_dir=str(summary_path.parent),
            scrape_error_message=result.error_message,
            scrape_successful_pages=result.successful_pages,
        )
        totals["raw_records_stored"] += _int_result(persisted["raw_records_stored"])
        totals["canonical_meetings_upserted"] += _int_result(
            persisted["canonical_meetings_upserted"]
        )
        console.print(
            f"  stored={persisted['raw_records_stored']} "
            f"canonical={persisted['canonical_meetings_upserted']} "
            f"run={persisted['import_run_id']}"
        )
    console.print("Totals")
    console.print(f"records_extracted: {totals['records_extracted']}")
    console.print(f"records_fetched: {totals['records_fetched']}")
    console.print(f"candidates_normalized: {totals['candidates_normalized']}")
    console.print(f"review_flags: {totals['review_flags']}")
    if dry_run:
        console.print("output: not written because --dry-run was set")
        return
    console.print(f"raw_records_stored: {totals['raw_records_stored']}")
    console.print(f"canonical_meetings_upserted: {totals['canonical_meetings_upserted']}")


@app.command("classify-sources")
def classify_sources(
    dry_run: bool = True,
    fellowship: Annotated[
        str | None,
        typer.Option(help="Only classify sources for this fellowship."),
    ] = None,
    source_id: Annotated[
        str | None,
        typer.Option(help="Only classify one source ID."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(help="Maximum number of sources to classify."),
    ] = None,
    offset: Annotated[
        int,
        typer.Option(help="Number of classifiable sources to skip before applying --limit."),
    ] = 0,
    concurrency: Annotated[
        int,
        typer.Option(
            min=1,
            help="Maximum number of sources to classify concurrently.",
        ),
    ] = 1,
    include_configured: Annotated[
        bool,
        typer.Option(help="Also reclassify sources that already have an ingest adapter."),
    ] = False,
    retry_classified_unknown: Annotated[
        bool,
        typer.Option(help="Also retry unknown sources that already have a classification reason."),
    ] = False,
) -> None:
    settings = get_settings()
    with connect(settings) as connection:
        repository = SourceRepository(connection)
        sources = (
            [source]
            if source_id and (source := repository.get_source(source_id)) is not None
            else repository.list_sources(fellowship=fellowship)
        )

    if source_id and not sources:
        raise typer.BadParameter(f"source not found: {source_id}")
    if source_id is None and not include_configured:
        sources = [source for source in sources if source.adapter_type == AdapterType.UNKNOWN]
    if source_id is None and not retry_classified_unknown:
        sources = [source for source in sources if not _has_classification_reason(source)]
    if source_id is None:
        sources = _select_scrape_batch(sources, offset=offset, limit=limit)
    if limit is not None:
        sources = sources[:limit]

    console.print(f"Source classification dry_run={dry_run}")
    console.print(f"sources: {len(sources)}")
    results = asyncio.run(_classify_sources(settings, sources, concurrency=concurrency))

    for result in results:
        source = result.source
        changed = "changed" if result.changed else "unchanged"
        console.print(
            f"- {source.id} {changed} adapter={source.adapter_type} reason={result.reason}"
        )

    if dry_run:
        console.print("output: not written because --dry-run was set")
        return

    with connect(settings) as connection:
        repository = SourceRepository(connection)
        stored = [repository.upsert_source(result.source) for result in results if result.changed]
        connection.commit()
    console.print(f"stored_sources: {len(stored)}")


@app.command("export-snapshot")
def export_snapshot(
    dry_run: bool = True,
    max_residual_duplicate_rate: Annotated[
        float,
        typer.Option(
            help=(
                "Maximum allowed semantic duplicate rate after export-time consolidation. "
                "Set higher only after reviewing printed duplicate examples."
            ),
        ),
    ] = 0.005,
    min_meetings: Annotated[
        int,
        typer.Option(help="Minimum consolidated meeting count required before writing a snapshot."),
    ] = 1,
) -> None:
    settings = get_settings()
    with connect(settings) as connection:
        canonical_repository = CanonicalMeetingRepository(connection)
        review_repository = ReviewFlagRepository(connection)
        candidates = canonical_repository.list_active_candidates_for_snapshot()
        blocked_by_review = review_repository.count_open_error_flags()
    build_result = build_snapshot_with_quality(candidates)
    snapshot = build_result.snapshot
    consolidation = build_result.consolidation
    residual = consolidate_duplicate_candidates(consolidation.candidates)
    console.print("Snapshot dry run" if dry_run else "Snapshot export")
    console.print(f"source_meetings: {consolidation.metrics.original_count}")
    console.print(f"active_meetings: {len(snapshot.meetings)}")
    console.print("stale_meetings: 0")
    console.print(f"blocked_by_review: {blocked_by_review}")
    _print_duplicate_metrics("duplicate_metrics", consolidation.metrics)
    _print_duplicate_metrics("residual_duplicate_metrics", residual.metrics)
    for example in consolidation.examples[:5]:
        console.print(
            "duplicate_example: "
            f"fellowship={example.fellowship} removed={example.removed_count} "
            f"name={example.name!r} sources={','.join(example.source_ids[:5])}"
        )
    residual_rate = (
        residual.metrics.removed_count / residual.metrics.original_count
        if residual.metrics.original_count
        else 0.0
    )
    gate_errors = []
    if len(snapshot.meetings) < min_meetings:
        gate_errors.append(
            f"consolidated meeting count {len(snapshot.meetings)} is below minimum {min_meetings}"
        )
    if residual_rate > max_residual_duplicate_rate:
        gate_errors.append(
            "residual duplicate rate "
            f"{residual_rate:.4%} exceeds maximum {max_residual_duplicate_rate:.4%}"
        )
    if gate_errors:
        for error in gate_errors:
            console.print(f"quality_gate_error: {error}")
        console.print("output: not written because snapshot quality gate failed")
        raise typer.Exit(1)
    if dry_run:
        console.print("output: not written because --dry-run was set")
        return
    path = write_snapshot_file(snapshot, settings.snapshot_output_dir)
    try:
        with connect(settings) as connection:
            snapshot_id = SnapshotRepository(connection).record_snapshot(
                schema_version=snapshot.schema_version,
                path=str(path),
                meeting_count=len(snapshot.meetings),
                blocked_by_review_count=blocked_by_review,
                generated_at=snapshot.generated_at,
            )
            connection.commit()
    except Exception:
        snapshot_id = "not recorded"
    console.print(f"output: {path}")
    console.print(f"snapshot_id: {snapshot_id}")


@app.command("audit-snapshot-quality")
def audit_snapshot_quality(
    snapshot_path: Annotated[Path, typer.Argument(help="Snapshot JSON file to audit.")],
    examples: Annotated[
        int,
        typer.Option(help="Maximum examples to print for each issue type."),
    ] = 5,
    top_sources: Annotated[
        int,
        typer.Option(help="Maximum source IDs to print for each aggregate list."),
    ] = 20,
) -> None:
    snapshot = Snapshot.model_validate_json(snapshot_path.read_text(encoding="utf-8"))
    audit = audit_snapshot_meetings(snapshot.meetings, max_examples_per_issue=examples)
    duplicate_audit = consolidate_duplicate_candidates(
        [_candidate_from_snapshot_meeting(meeting) for meeting in snapshot.meetings],
        max_examples=examples,
    )

    console.print(f"snapshot: {snapshot_path}")
    console.print(f"total_meetings: {audit.total_meetings}")
    _print_duplicate_metrics("duplicate_metrics", duplicate_audit.metrics)
    for duplicate_example in duplicate_audit.examples:
        console.print(
            "duplicate_example: "
            f"fellowship={duplicate_example.fellowship} "
            f"removed={duplicate_example.removed_count} "
            f"name={duplicate_example.name!r} "
            f"sources={','.join(duplicate_example.source_ids[:5])}"
        )
    _print_counter("country_aliases", audit.country_aliases, top_sources)
    _print_counter("issue_counts", audit.issue_counts, top_sources)
    _print_counter("issue_counts_by_fellowship", audit.issue_counts_by_fellowship, top_sources)
    _print_counter("issue_counts_by_source", audit.issue_counts_by_source, top_sources)
    for issue_code, issue_examples in sorted(audit.examples.items()):
        console.print(f"{issue_code}_examples:")
        for issue_example in issue_examples:
            console.print(json.dumps(issue_example.as_dict(), ensure_ascii=False, sort_keys=True))


def _print_counter(label: str, counter: Counter[str], limit: int) -> None:
    console.print(f"{label}:")
    if not counter:
        console.print("- none")
        return
    for key, count in counter.most_common(limit):
        console.print(f"- {count} {key}")


def _print_duplicate_metrics(label: str, metrics: DuplicateMetrics) -> None:
    console.print(f"{label}:")
    console.print(f"- original_count: {metrics.original_count}")
    console.print(f"- consolidated_count: {metrics.consolidated_count}")
    console.print(f"- removed_count: {metrics.removed_count}")
    _print_metric_dict(
        "- exact_occurrence_duplicate_groups_by_fellowship",
        metrics.exact_occurrence_duplicate_groups_by_fellowship,
    )
    _print_metric_dict(
        "- semantic_duplicate_groups_by_fellowship",
        metrics.semantic_duplicate_groups_by_fellowship,
    )
    _print_metric_dict("- removed_by_fellowship", metrics.removed_by_fellowship)


def _print_metric_dict(label: str, values: dict[str, int]) -> None:
    rendered = ", ".join(f"{key}={values[key]}" for key in sorted(values))
    console.print(f"{label}: {rendered or 'none'}")


def _candidate_from_snapshot_meeting(meeting: SnapshotMeeting) -> CanonicalMeetingCandidate:
    return CanonicalMeetingCandidate(**meeting.model_dump())


@app.command("cleanup-timezones")
def cleanup_timezones(
    dry_run: bool = True,
    fellowship: Annotated[
        str | None,
        typer.Option(help="Only clean missing timezone warnings for this fellowship."),
    ] = None,
    source_id: Annotated[
        str | None,
        typer.Option(help="Only clean one source ID."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(help="Maximum sources to process."),
    ] = None,
    concurrency: Annotated[
        int,
        typer.Option(
            min=1,
            help="Maximum number of sources to clean concurrently.",
        ),
    ] = 1,
) -> None:
    settings = get_settings()
    with connect(settings) as connection:
        source_ids = _timezone_cleanup_source_ids(
            connection,
            fellowship=fellowship,
            source_id=source_id,
            limit=limit,
        )

    console.print(f"Timezone cleanup dry_run={dry_run}")
    console.print(f"sources: {len(source_ids)}")
    results = asyncio.run(
        _cleanup_timezone_sources(
            settings,
            source_ids,
            dry_run=dry_run,
            concurrency=concurrency,
        )
    )
    totals = {
        "meetings_scanned": 0,
        "meetings_fixed": 0,
        "occurrences_updated": 0,
        "flags_resolved": 0,
        "meetings_unresolved": 0,
    }
    for result in results:
        for key in totals:
            value = result[key]
            if isinstance(value, int):
                totals[key] += value
        console.print(
            f"- {result['source_id']} scanned={result['meetings_scanned']} "
            f"fixed={result['meetings_fixed']} occurrences={result['occurrences_updated']} "
            f"resolved={result['flags_resolved']} unresolved={result['meetings_unresolved']}"
        )
    console.print("Totals")
    for key, value in totals.items():
        console.print(f"{key}: {value}")
    if dry_run:
        console.print("output: not written because --dry-run was set")


def _timezone_cleanup_source_ids(
    connection: Connection[Any],
    *,
    fellowship: str | None,
    source_id: str | None,
    limit: int | None,
) -> list[str]:
    query = """
        SELECT rf.source_id, COUNT(*) AS warning_count
        FROM review_flags rf
        JOIN canonical_meetings cm
          ON cm.source_id = rf.source_id
         AND cm.source_record_id = rf.source_record_id
        JOIN sources s ON s.id = rf.source_id
        WHERE rf.status = 'open'
          AND rf.code = 'missing_timezone'
          AND EXISTS (
              SELECT 1
              FROM meeting_occurrences mo
              WHERE mo.canonical_meeting_id = cm.id
                AND mo.timezone = 'UTC'
          )
    """
    params: dict[str, object] = {}
    if fellowship is not None:
        query += " AND COALESCE(cm.fellowship, s.fellowship) = %(fellowship)s"
        params["fellowship"] = fellowship
    if source_id is not None:
        query += " AND rf.source_id = %(source_id)s"
        params["source_id"] = source_id
    query += " GROUP BY rf.source_id ORDER BY warning_count DESC, rf.source_id"
    if limit is not None:
        query += " LIMIT %(limit)s"
        params["limit"] = limit
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        return [str(row[0]) for row in cursor.fetchall()]


async def _cleanup_timezone_sources(
    settings: Settings,
    source_ids: list[str],
    *,
    dry_run: bool,
    concurrency: int,
) -> list[dict[str, object]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: list[dict[str, object] | None] = [None] * len(source_ids)

    async def cleanup_one(index: int, source_id: str) -> None:
        async with semaphore:
            results[index] = await asyncio.to_thread(
                _cleanup_timezone_source,
                settings,
                source_id,
                dry_run,
            )

    await asyncio.gather(
        *(cleanup_one(index, source_id) for index, source_id in enumerate(source_ids))
    )
    return [result for result in results if result is not None]


def _cleanup_timezone_source(
    settings: Settings,
    source_id: str,
    dry_run: bool,
) -> dict[str, object]:
    with connect(settings) as connection:
        rows = _timezone_cleanup_rows(connection, source_id)
        meetings_fixed = 0
        occurrences_updated = 0
        flags_resolved = 0
        unresolved = 0
        for row in rows:
            timezone = _timezone_for_cleanup_row(row)
            if timezone is None:
                unresolved += 1
                continue
            meetings_fixed += 1
            if dry_run:
                continue
            occurrences_updated += _update_meeting_utc_occurrences(
                connection,
                str(row["meeting_id"]),
                timezone,
            )
            flags_resolved += _resolve_missing_timezone_flags(
                connection,
                source_id,
                str(row["source_record_id"]),
            )
        if not dry_run:
            connection.commit()
    return {
        "source_id": source_id,
        "meetings_scanned": len(rows),
        "meetings_fixed": meetings_fixed,
        "occurrences_updated": occurrences_updated,
        "flags_resolved": flags_resolved,
        "meetings_unresolved": unresolved,
    }


def _timezone_cleanup_rows(
    connection: Connection[Any],
    source_id: str,
) -> list[dict[str, object]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT DISTINCT
                cm.id AS meeting_id,
                cm.source_record_id,
                cm.name AS meeting_name,
                cm.city AS meeting_city,
                cm.region AS meeting_region,
                cm.country AS meeting_country,
                s.name AS source_name,
                s.url AS source_url,
                s.country AS source_country,
                s.region AS source_region,
                s.config AS source_config
            FROM review_flags rf
            JOIN canonical_meetings cm
              ON cm.source_id = rf.source_id
             AND cm.source_record_id = rf.source_record_id
            JOIN sources s ON s.id = rf.source_id
            WHERE rf.status = 'open'
              AND rf.code = 'missing_timezone'
              AND rf.source_id = %(source_id)s
              AND EXISTS (
                  SELECT 1
                  FROM meeting_occurrences mo
                  WHERE mo.canonical_meeting_id = cm.id
                    AND mo.timezone = 'UTC'
              )
            ORDER BY cm.source_record_id
            """,
            {"source_id": source_id},
        )
        return [dict(row) for row in cursor.fetchall()]


def _timezone_for_cleanup_row(row: dict[str, object]) -> str | None:
    source_config = row.get("source_config")
    configured_timezone = None
    if isinstance(source_config, dict):
        value = source_config.get("timezone")
        if isinstance(value, str) and value.strip() and value.strip() != "UTC":
            configured_timezone = value.strip()
    meeting_country = _cleanup_string(row.get("meeting_country"))
    meeting_region = _cleanup_string(row.get("meeting_region"))
    source_country = _cleanup_string(row.get("source_country"))
    source_region = _cleanup_string(row.get("source_region"))
    source_name = _cleanup_string(row.get("source_name"))
    source_url = _cleanup_string(row.get("source_url"))
    return (
        configured_timezone
        or timezone_for_country_region(meeting_country, meeting_region)
        or timezone_for_country_region(source_country, meeting_region)
        or timezone_for_country_region(source_country, source_region)
        or timezone_for_country_region(None, meeting_region)
        or timezone_for_country_region(None, source_region)
        or timezone_for_source_text(source_name, source_url)
    )


def _cleanup_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _update_meeting_utc_occurrences(
    connection: Connection[Any],
    meeting_id: str,
    timezone: str,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE meeting_occurrences
            SET timezone = %(timezone)s
            WHERE canonical_meeting_id = %(meeting_id)s
              AND timezone = 'UTC'
            """,
            {"meeting_id": meeting_id, "timezone": timezone},
        )
        return cursor.rowcount


def _resolve_missing_timezone_flags(
    connection: Connection[Any],
    source_id: str,
    source_record_id: str,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE review_flags
            SET status = 'resolved',
                resolved_at = NOW()
            WHERE source_id = %(source_id)s
              AND source_record_id = %(source_record_id)s
              AND code = 'missing_timezone'
              AND status = 'open'
            """,
            {"source_id": source_id, "source_record_id": source_record_id},
        )
        return cursor.rowcount


def _artifact_source_metadata_by_id(
    settings: Settings,
    artifact_dir: Path,
) -> dict[str, dict[str, Any]]:
    stored = _stored_source_metadata_by_id(settings)
    artifact = source_metadata_by_id(artifact_dir)
    merged = dict(stored)
    for source_id, metadata in artifact.items():
        base = dict(merged.get(source_id, {}))
        base_config = base.get("config")
        metadata_config = metadata.get("config")
        merged_config = None
        if isinstance(base_config, dict) or isinstance(metadata_config, dict):
            merged_config = {
                **(base_config if isinstance(base_config, dict) else {}),
                **(metadata_config if isinstance(metadata_config, dict) else {}),
            }
        base.update(metadata)
        if merged_config is not None:
            base["config"] = merged_config
        merged[source_id] = base
    return merged


def _stored_source_metadata_by_id(settings: Settings) -> dict[str, dict[str, Any]]:
    try:
        with connect(settings) as connection:
            sources = SourceRepository(connection).list_sources()
    except Exception:
        return {}
    return {
        source.id: {
            "source_id": source.id,
            "fellowship": source.fellowship,
            "name": source.name,
            "url": source.url,
            "country": source.country,
            "region": source.region,
            "timezone": source.config.get("timezone"),
            "config": source.config,
        }
        for source in sources
    }


@app.command("report")
def report() -> None:
    settings = get_settings()
    console.print("Recovery meeting ingestion report")
    try:
        with connect(settings) as connection:
            source_count = SourceRepository(connection).count_sources()
            meeting_count = CanonicalMeetingRepository(connection).count_meetings()
            review_count = ReviewFlagRepository(connection).count_open_flags()
    except Exception:
        source_count = 0
        meeting_count = 0
        review_count = 0
    console.print(f"sources: {source_count}")
    console.print(f"active_meetings: {meeting_count}")
    console.print(f"review_flags: {review_count}")


def main() -> None:
    app()


def _discovery_for(fellowship: str, settings: Settings, url: str | None) -> SourceDiscovery:
    if fellowship == "aa":
        return (
            AaWorldServicesDiscovery(settings, url=url)
            if url
            else AaWorldServicesDiscovery(settings)
        )
    if fellowship == "ca":
        return (
            CaWorldServicesDiscovery(settings, url=url)
            if url
            else CaWorldServicesDiscovery(settings)
        )
    if fellowship == "na":
        return (
            NaWorldServicesDiscovery(settings, url=url)
            if url
            else NaWorldServicesDiscovery(settings)
        )
    raise typer.BadParameter("fellowship must be aa, ca, or na")


async def _classify_sources(
    settings: Settings,
    sources: list[Source],
    *,
    concurrency: int = 1,
) -> list[ClassificationResult]:
    classifier = SourceProbeClassifier(user_agent=settings.user_agent)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: list[ClassificationResult | None] = [None] * len(sources)

    async def classify_one(index: int, source: Source) -> None:
        async with semaphore:
            results[index] = await _classify_one_source(classifier, source)
            if settings.default_rate_limit_seconds > 0 and concurrency == 1:
                await asyncio.sleep(settings.default_rate_limit_seconds)

    await asyncio.gather(*(classify_one(index, source) for index, source in enumerate(sources)))
    return [result for result in results if result is not None]


async def _classify_one_source(
    classifier: SourceProbeClassifier,
    source: Source,
) -> ClassificationResult:
    try:
        return await classifier.classify(source)
    except Exception as exc:
        failed = source.model_copy(
            update={
                "config": {
                    **source.config,
                    "classification": {"reason": f"classification failed: {exc}"},
                }
            }
        )
        return ClassificationResult(
            source=failed,
            changed=True,
            reason=f"classification failed: {exc}",
        )


def _is_ingestable_source(source: Source) -> bool:
    return source.adapter_type in {
        AdapterType.MEETING_GUIDE,
        AdapterType.BMLT,
        AdapterType.STATIC_HTML,
        AdapterType.FORM_HTTP,
        AdapterType.PLAYWRIGHT_BROWSER,
    }


def _source_for_ingest(
    source_id: str,
    settings: Settings,
    fixture: Path | None,
    adapter: AdapterType | None,
    fellowship: str,
    source_url: str,
) -> Source:
    if fixture is not None:
        if adapter is None:
            raise typer.BadParameter("--adapter is required when --fixture is provided")
        return Source(
            id=source_id,
            fellowship=fellowship,  # type: ignore[arg-type]
            name=source_id,
            url=source_url,
            source_type=SourceType.MEETING_FEED,
            adapter_type=adapter,
        )

    with connect(settings) as connection:
        source = SourceRepository(connection).get_source(source_id)
    if source is None:
        raise typer.BadParameter(f"source not found: {source_id}")
    return source


def _source_for_scrape(
    source_id: str,
    settings: Settings,
    fixture: Path | None,
    adapter: AdapterType,
    fellowship: str,
    source_url: str,
) -> Source:
    if fixture is not None:
        return Source(
            id=source_id,
            fellowship=fellowship,  # type: ignore[arg-type]
            name=source_id,
            url=source_url,
            source_type=SourceType.LOCAL_SERVICE_BODY,
            adapter_type=adapter,
            requires_browser=adapter == AdapterType.PLAYWRIGHT_BROWSER,
        )

    with connect(settings) as connection:
        source = SourceRepository(connection).get_source(source_id)
    if source is None:
        raise typer.BadParameter(f"source not found: {source_id}")
    return _as_browser_scrape_source(source)


async def _scrape_source(
    source: Source,
    settings: Settings,
    *,
    fixture: Path | None,
    crawl_settings: CrawlSettings,
    output_dir: Path | None,
) -> ScrapeResult:
    if fixture is None and _uses_direct_ingest_for_scrape(source):
        ingest_result = await run_ingest_source(source, settings)
        return ScrapeResult(
            scrape=ScrapeSourceResult(
                source_id=source.id,
                source_url=source.url,
                status="succeeded",
            ),
            ingest=ingest_result,
        )
    if fixture is None:
        return await run_scrape_source(
            source,
            settings,
            crawl_settings=crawl_settings,
            artifact_dir=output_dir,
        )
    html = fixture.read_text(encoding="utf-8")
    extracted = extract_meetings_from_html(
        html,
        source_page_url=source.url,
        source_config=source.config,
    )
    scrape = ScrapeSourceResult(
        source_id=source.id,
        source_url=source.url,
        status="succeeded",
        pages=[
            ScrapedPage(
                url=source.url,
                final_url=source.url,
                title=fixture.name,
                html=html,
                extracted=extracted,
            )
        ],
    )
    if output_dir is not None and crawl_settings.save_artifacts:
        artifact_path = write_scrape_evidence(scrape, output_dir)
        scrape = ScrapeSourceResult(
            source_id=scrape.source_id,
            source_url=scrape.source_url,
            status=scrape.status,
            pages=scrape.pages,
            artifact_dir=str(artifact_path),
        )
    ingest_result = await run_ingest_source(source, settings, fixture=fixture)
    return ScrapeResult(scrape=scrape, ingest=ingest_result)


async def _scrape_sources(
    sources: list[Source],
    settings: Settings,
    *,
    dry_run: bool,
    crawl_settings: CrawlSettings,
    output_dir: Path | None,
    concurrency: int,
) -> None:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    persist_lock = asyncio.Lock()
    print_lock = asyncio.Lock()
    completed = 0
    total = len(sources)

    async def scrape_one(source: Source) -> None:
        nonlocal completed
        try:
            async with semaphore:
                result = await _scrape_source(
                    source,
                    settings,
                    fixture=None,
                    crawl_settings=crawl_settings,
                    output_dir=output_dir,
                )
            persisted: dict[str, object] | None = None
            if not dry_run:
                async with persist_lock:
                    persisted = await asyncio.to_thread(
                        _persist_ingest_result,
                        settings,
                        source,
                        result.ingest,
                        scrape=result.scrape,
                    )
            async with print_lock:
                _print_scrape_result(f"- {source.id}", dry_run, source, result)
                if persisted is not None:
                    console.print(
                        f"  stored={persisted['raw_records_stored']} "
                        f"canonical={persisted['canonical_meetings_upserted']} "
                        f"run={persisted['import_run_id']}"
                    )
        except Exception as exc:
            async with print_lock:
                console.print(f"- {source.id} failed: {exc}")
        finally:
            completed += 1
            async with print_lock:
                console.print(f"progress: {completed}/{total}")

    await asyncio.gather(*(scrape_one(source) for source in sources))


def _source_for_scrape_all(source: Source) -> Source:
    if _uses_direct_ingest_for_scrape(source):
        return source
    return _as_browser_scrape_source(source)


def _uses_direct_ingest_for_scrape(source: Source) -> bool:
    return source.adapter_type in {AdapterType.BMLT, AdapterType.MEETING_GUIDE}


def _as_browser_scrape_source(source: Source) -> Source:
    if source.adapter_type in {
        AdapterType.PLAYWRIGHT_BROWSER,
        AdapterType.STATIC_HTML,
        AdapterType.FORM_HTTP,
    }:
        config = source.config
    else:
        existing_scrape = source.config.get("scrape")
        scrape_config = existing_scrape if isinstance(existing_scrape, dict) else {}
        config = {
            **source.config,
            "scrape": {
                **scrape_config,
                "previous_adapter_type": source.adapter_type.value,
            },
        }
    return source.model_copy(
        update={
            "source_type": (
                SourceType.WORLD_SERVICE_LISTING
                if source.source_type == SourceType.WORLD_SERVICE_LISTING
                else SourceType.LOCAL_SERVICE_BODY
            ),
            "adapter_type": AdapterType.PLAYWRIGHT_BROWSER,
            "requires_browser": True,
            "config": config,
        }
    )


def _is_scrapeable_source(
    source: Source,
    *,
    include_classified_unknown: bool = False,
) -> bool:
    if source.source_type == SourceType.WORLD_SERVICE_LISTING:
        return source.fellowship == "ca"
    if (
        source.adapter_type == AdapterType.UNKNOWN
        and _has_classification_reason(source)
        and not include_classified_unknown
    ):
        return False
    return (
        source.source_type
        not in {
            SourceType.PHONE,
            SourceType.PDF,
        }
        and not source.url.startswith("tel:")
    )


def _select_scrape_batch(
    sources: list[Source],
    *,
    offset: int = 0,
    limit: int | None = None,
) -> list[Source]:
    start = max(0, offset)
    selected = sources[start:]
    if limit is not None:
        return selected[:limit]
    return selected


def _zero_active_browser_sources(connection: Connection[Any], fellowship: str) -> list[Source]:
    active_counts = _active_meeting_counts_by_source(connection, fellowship)
    sources = SourceRepository(connection).list_sources(fellowship=fellowship)
    return [
        source
        for source in sources
        if source.adapter_type == AdapterType.PLAYWRIGHT_BROWSER
        and active_counts.get(source.id, 0) == 0
    ]


def _active_meeting_counts_by_source(
    connection: Connection[Any],
    fellowship: str,
) -> dict[str, int]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT source_id, COUNT(*) AS meeting_count
            FROM canonical_meetings
            WHERE fellowship = %(fellowship)s
              AND status = 'active'
            GROUP BY source_id
            """,
            {"fellowship": fellowship},
        )
        return {str(row["source_id"]): int(row["meeting_count"]) for row in cursor.fetchall()}


def _zero_source_retry_command(
    source_ids: list[str],
    *,
    fellowship: str,
    concurrency: int,
    max_pages_per_source: int,
) -> str:
    source_args = " ".join(f"--source-id {source_id}" for source_id in source_ids)
    return (
        "PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/"
        ".playwright-browsers .venv/bin/python -m app.cli scrape-all "
        f"--fellowship {fellowship} --no-dry-run --concurrency {concurrency} "
        f"--max-pages-per-source {max_pages_per_source} "
        f"--output-dir scrape_artifacts/{fellowship}-curated-zero-retry-YYYYMMDDTHHMMSSZ "
        f"{source_args}"
    ).strip()


def _filter_sources_by_ids(
    sources: list[Source],
    source_ids: list[str] | None,
) -> list[Source]:
    if not source_ids:
        return sources
    wanted = set(source_ids)
    return [source for source in sources if source.id in wanted]


def _filter_sources_for_scrape_retry(
    sources: list[Source],
    *,
    only_failed: bool = False,
    only_zero_records: bool = False,
) -> list[Source]:
    if not only_failed and not only_zero_records:
        return sources
    return [
        source
        for source in sources
        if (only_failed and _source_last_scrape_failed(source))
        or (only_zero_records and _source_last_scrape_zero_records(source))
    ]


def _ca_world_listings_shadowed_by_local_sources(sources: list[Source]) -> set[str]:
    local_world_sources = {
        normalize_source_url(world_source)
        for source in sources
        if source.fellowship == "ca"
        and source.source_type != SourceType.WORLD_SERVICE_LISTING
        if (world_source := _source_metadata_world_source(source))
    }
    return {
        source.id
        for source in sources
        if source.fellowship == "ca"
        and source.source_type == SourceType.WORLD_SERVICE_LISTING
        and normalize_source_url(source.url) in local_world_sources
    }


def _source_metadata_world_source(source: Source) -> str | None:
    metadata = source.config.get("metadata")
    if not isinstance(metadata, dict):
        return None
    world_source = metadata.get("world_source")
    if not isinstance(world_source, str):
        return None
    return world_source.strip() or None


def _has_classification_reason(source: Source) -> bool:
    classification = source.config.get("classification")
    if not isinstance(classification, dict):
        return False
    reason = classification.get("reason")
    return isinstance(reason, str) and bool(reason.strip())


def _source_last_scrape_failed(source: Source) -> bool:
    scrape_config = source.config.get("scrape")
    if not isinstance(scrape_config, dict):
        return False
    return scrape_config.get("last_status") == "failed"


def _source_last_scrape_zero_records(source: Source) -> bool:
    if _uses_direct_ingest_for_scrape(source):
        return False
    scrape_config = source.config.get("scrape")
    if not isinstance(scrape_config, dict):
        return False
    if scrape_config.get("last_status") != "succeeded":
        return False
    try:
        return int(scrape_config.get("last_records_extracted", -1)) == 0
    except (TypeError, ValueError):
        return False


def _source_with_scrape_metadata(source: Source, scrape: ScrapeSourceResult) -> Source:
    return _source_with_scrape_status(
        source,
        status=scrape.status,
        pages_visited=scrape.pages_visited,
        records_extracted=scrape.records_extracted,
        artifact_dir=scrape.artifact_dir,
        error_message=scrape.error_message,
        successful_pages=_successful_pages_from_scrape(scrape),
    )


def _source_with_scrape_status(
    source: Source,
    *,
    status: str,
    pages_visited: int,
    records_extracted: int,
    artifact_dir: str | None = None,
    error_message: str | None = None,
    successful_pages: list[dict[str, object]] | None = None,
) -> Source:
    existing = source.config.get("scrape")
    scrape_config = dict(existing) if isinstance(existing, dict) else {}
    scrape_config.update(
        {
            "last_status": status,
            "last_pages_visited": pages_visited,
            "last_records_extracted": records_extracted,
        }
    )
    if artifact_dir:
        scrape_config["last_artifact_dir"] = artifact_dir
    else:
        scrape_config.pop("last_artifact_dir", None)
    if error_message:
        scrape_config["last_error"] = error_message[:500]
    else:
        scrape_config.pop("last_error", None)
    if successful_pages:
        scrape_config["successful_pages"] = successful_pages[:5]
        first_page = successful_pages[0]
        url = first_page.get("url")
        if isinstance(url, str):
            scrape_config["last_successful_page_url"] = url
        records = first_page.get("records_extracted")
        if isinstance(records, int):
            scrape_config["last_successful_page_records"] = records
        signals = first_page.get("signals")
        if isinstance(signals, list):
            scrape_config["last_successful_page_signals"] = signals
    elif status == "succeeded" and records_extracted == 0:
        scrape_config.pop("successful_pages", None)
        scrape_config.pop("last_successful_page_url", None)
        scrape_config.pop("last_successful_page_records", None)
        scrape_config.pop("last_successful_page_signals", None)
    updates: dict[str, object] = {"config": {**source.config, "scrape": scrape_config}}
    previous_adapter = _previous_feed_adapter(scrape_config)
    if source.adapter_type == AdapterType.PLAYWRIGHT_BROWSER and previous_adapter is not None:
        updates.update(
            {
                "adapter_type": previous_adapter,
                "source_type": SourceType.MEETING_FEED,
                "requires_browser": False,
            }
        )
    return source.model_copy(update=updates)


def _previous_feed_adapter(scrape_config: dict[str, object]) -> AdapterType | None:
    value = scrape_config.get("previous_adapter_type")
    if not isinstance(value, str):
        return None
    try:
        adapter = AdapterType(value)
    except ValueError:
        return None
    if adapter in {AdapterType.BMLT, AdapterType.MEETING_GUIDE}:
        return adapter
    return None


def _successful_pages_from_scrape(scrape: ScrapeSourceResult) -> list[dict[str, object]]:
    pages = [
        {
            "url": page.final_url or page.url,
            "records_extracted": page.extracted_count,
            "score": page.page_score,
            "signals": page.page_signals,
        }
        for page in scrape.pages
        if page.extracted_count > 0 and (page.final_url or page.url)
    ]
    return _dedupe_successful_pages(pages)


def _dedupe_successful_pages(pages: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[str] = set()
    for page in sorted(
        pages,
        key=lambda item: (
            item.get("records_extracted") if isinstance(item.get("records_extracted"), int) else 0,
            item.get("score") if isinstance(item.get("score"), float | int) else 0,
        ),
        reverse=True,
    ):
        url = page.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        if url in seen:
            continue
        seen.add(url)
        deduped.append(page)
    return deduped[:5]


def _print_scrape_result(
    label: str,
    dry_run: bool,
    source: Source,
    result: ScrapeResult,
) -> None:
    console.print(f"{label} dry_run={dry_run}")
    console.print(f"source_id: {source.id}")
    console.print(f"adapter: {source.adapter_type}")
    console.print(f"scrape_status: {result.scrape.status}")
    console.print(f"pages_visited: {result.scrape.pages_visited}")
    console.print(f"records_extracted: {result.scrape.records_extracted}")
    console.print(f"records_fetched: {len(result.ingest.raw_records)}")
    console.print(f"candidates_normalized: {len(result.ingest.candidates)}")
    console.print(f"review_flags: {len(result.ingest.review_flags)}")
    if result.scrape.artifact_dir:
        console.print(f"artifact_dir: {result.scrape.artifact_dir}")
    if result.scrape.error_message:
        console.print(f"error: {result.scrape.error_message}")


def _persist_ingest_result(
    settings: Settings,
    source: Source,
    result: IngestResult,
    *,
    scrape: ScrapeSourceResult | None = None,
    scrape_status: str | None = None,
    scrape_pages_visited: int = 0,
    scrape_records_extracted: int = 0,
    scrape_artifact_dir: str | None = None,
    scrape_error_message: str | None = None,
    scrape_successful_pages: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if scrape is not None:
        source = _source_with_scrape_metadata(source, scrape)
    elif scrape_status is not None:
        source = _source_with_scrape_status(
            source,
            status=scrape_status,
            pages_visited=scrape_pages_visited,
            records_extracted=scrape_records_extracted,
            artifact_dir=scrape_artifact_dir,
            error_message=scrape_error_message,
            successful_pages=scrape_successful_pages,
        )
    scrape_failed = (scrape is not None and scrape.status == "failed") or scrape_status == "failed"
    with connect(settings) as connection:
        source_repository = SourceRepository(connection)
        stored_source = source_repository.upsert_source(source)
        run_repository = ImportRunRepository(connection)
        run = run_repository.start(stored_source.id)
        if scrape_failed:
            finished_run = run_repository.finish(
                run.id,
                status="failed",
                records_fetched=0,
                records_changed=0,
                review_flags_created=0,
                error_message=(
                    scrape.error_message
                    if scrape is not None
                    else scrape_error_message
                ),
            )
            connection.commit()
            return {
                "raw_records_stored": 0,
                "canonical_meetings_upserted": 0,
                "meetings_marked_missing": 0,
                "review_flags_created": 0,
                "import_run_id": finished_run.id,
            }
        raw_repository = RawMeetingRepository(connection)
        canonical_repository = CanonicalMeetingRepository(connection)
        review_repository = ReviewFlagRepository(connection)
        try:
            previous_active_count = canonical_repository.count_active_for_source(stored_source.id)
            stored = raw_repository.upsert_raw_meetings(result.raw_records)
            canonical_changed = canonical_repository.upsert_candidates(result.candidates)
            stale_marked = canonical_repository.mark_missing_for_source(
                stored_source.id,
                {candidate.source_record_id for candidate in result.candidates},
            )
            review_flags = list(result.review_flags)
            source_drop_flag = flag_source_drop(previous_active_count, len(result.candidates))
            if source_drop_flag is not None:
                review_flags.append(source_drop_flag)
            review_flags_created = review_repository.replace_flags_for_source(
                stored_source.id,
                review_flags,
            )
            finished_run = run_repository.finish(
                run.id,
                status="succeeded",
                records_fetched=len(result.raw_records),
                records_changed=stored,
                review_flags_created=review_flags_created,
            )
        except Exception as exc:
            run_repository.finish(
                run.id,
                status="failed",
                records_fetched=len(result.raw_records),
                records_changed=0,
                review_flags_created=0,
                error_message=str(exc),
            )
            raise
        connection.commit()
    return {
        "raw_records_stored": stored,
        "canonical_meetings_upserted": canonical_changed,
        "meetings_marked_missing": stale_marked,
        "review_flags_created": review_flags_created,
        "import_run_id": finished_run.id,
    }


def _print_persisted_result(result: dict[str, object]) -> None:
    console.print(f"raw_records_stored: {result['raw_records_stored']}")
    console.print(f"canonical_meetings_upserted: {result['canonical_meetings_upserted']}")
    console.print(f"meetings_marked_missing: {result['meetings_marked_missing']}")
    console.print(f"review_flags_created: {result['review_flags_created']}")
    console.print(f"import_run_id: {result['import_run_id']}")


def _int_result(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"expected integer result, got {type(value).__name__}")


if __name__ == "__main__":
    main()

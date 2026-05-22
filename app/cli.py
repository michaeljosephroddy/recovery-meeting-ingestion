import asyncio
from pathlib import Path
from typing import Annotated, Any, Protocol, runtime_checkable

import typer
from psycopg import Connection
from rich.console import Console

from app.config import Settings, get_settings
from app.export.snapshot import build_snapshot
from app.export.snapshot import write_snapshot as write_snapshot_file
from app.ingest import IngestResult
from app.ingest import ingest_source as run_ingest_source
from app.logging import configure_logging
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
    persisted = _persist_ingest_result(settings, source, result.ingest)
    _print_persisted_result(persisted)


@app.command("scrape-all")
def scrape_all(
    dry_run: bool = True,
    fellowship: Annotated[
        str | None,
        typer.Option(help="Only scrape sources for this fellowship."),
    ] = None,
    limit: Annotated[int | None, typer.Option(help="Maximum sources to scrape.")] = None,
    max_pages_per_source: Annotated[
        int,
        typer.Option(help="Maximum pages to visit per source."),
    ] = 20,
    only_unknown: Annotated[
        bool,
        typer.Option(help="Only scrape sources without a configured ingest adapter."),
    ] = False,
    include_failed: Annotated[
        bool,
        typer.Option(help="Also retry sources with previous scrape failure metadata."),
    ] = False,
    save_artifacts: Annotated[
        bool,
        typer.Option(help="Write scrape artifacts for each source."),
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
    with connect(settings) as connection:
        sources = SourceRepository(connection).list_sources(fellowship=fellowship)
    if only_unknown:
        sources = [source for source in sources if source.adapter_type == AdapterType.UNKNOWN]
    if not include_failed:
        sources = [source for source in sources if not _source_last_scrape_failed(source)]
    shadowed_world_listing_ids = _ca_world_listings_shadowed_by_local_sources(sources)
    scrapeable = [
        _as_browser_scrape_source(source)
        for source in sources
        if _is_scrapeable_source(source) and source.id not in shadowed_world_listing_ids
    ]
    if limit is not None:
        scrapeable = scrapeable[:limit]

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
    for source in scrapeable:
        try:
            result = asyncio.run(
                _scrape_source(
                    source,
                    settings,
                    fixture=None,
                    crawl_settings=crawl_settings,
                    output_dir=output_dir if save_artifacts else None,
                )
            )
            _print_scrape_result(f"- {source.id}", dry_run, source, result)
            if not dry_run:
                persisted = _persist_ingest_result(settings, source, result.ingest)
                console.print(
                    f"  stored={persisted['raw_records_stored']} "
                    f"canonical={persisted['canonical_meetings_upserted']} "
                    f"run={persisted['import_run_id']}"
                )
        except Exception as exc:
            console.print(f"- {source.id} failed: {exc}")


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
    metadata = source_metadata_by_id(artifact_dir if artifact_dir.is_dir() else artifact_dir.parent)
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
        persisted = _persist_ingest_result(settings, result.source, result.ingest)
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
    include_configured: Annotated[
        bool,
        typer.Option(help="Also reclassify sources that already have an ingest adapter."),
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
    if limit is not None:
        sources = sources[:limit]

    console.print(f"Source classification dry_run={dry_run}")
    console.print(f"sources: {len(sources)}")
    results = asyncio.run(_classify_sources(settings, sources))

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
def export_snapshot(dry_run: bool = True) -> None:
    settings = get_settings()
    try:
        with connect(settings) as connection:
            canonical_repository = CanonicalMeetingRepository(connection)
            review_repository = ReviewFlagRepository(connection)
            candidates = canonical_repository.list_active_candidates_for_snapshot()
            blocked_by_review = review_repository.count_open_error_flags()
    except Exception:
        candidates = []
        blocked_by_review = 0
    snapshot = build_snapshot(candidates)
    console.print("Snapshot dry run" if dry_run else "Snapshot export")
    console.print(f"active_meetings: {len(snapshot.meetings)}")
    console.print("stale_meetings: 0")
    console.print(f"blocked_by_review: {blocked_by_review}")
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
) -> list[ClassificationResult]:
    classifier = SourceProbeClassifier(user_agent=settings.user_agent)
    results = []
    for source in sources:
        try:
            results.append(await classifier.classify(source))
            if settings.default_rate_limit_seconds > 0:
                await asyncio.sleep(settings.default_rate_limit_seconds)
        except Exception as exc:
            failed = source.model_copy(
                update={
                    "config": {
                        **source.config,
                        "classification": {"reason": f"classification failed: {exc}"},
                    }
                }
            )
            results.append(
                ClassificationResult(
                    source=failed,
                    changed=True,
                    reason=f"classification failed: {exc}",
                )
            )
    return results


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


def _is_scrapeable_source(source: Source) -> bool:
    if source.source_type == SourceType.WORLD_SERVICE_LISTING:
        return source.fellowship == "ca"
    return (
        source.source_type
        not in {
            SourceType.PHONE,
            SourceType.PDF,
        }
        and not source.url.startswith("tel:")
    )


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


def _source_last_scrape_failed(source: Source) -> bool:
    scrape_config = source.config.get("scrape")
    if not isinstance(scrape_config, dict):
        return False
    return scrape_config.get("last_status") == "failed"


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
) -> dict[str, object]:
    with connect(settings) as connection:
        source_repository = SourceRepository(connection)
        stored_source = source_repository.upsert_source(source)
        run_repository = ImportRunRepository(connection)
        run = run_repository.start(stored_source.id)
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

import asyncio
from pathlib import Path
from typing import Annotated, Protocol, runtime_checkable

import typer
from rich.console import Console

from app.config import Settings, get_settings
from app.export.snapshot import build_snapshot
from app.export.snapshot import write_snapshot as write_snapshot_file
from app.ingest import IngestResult
from app.ingest import ingest_source as run_ingest_source
from app.logging import configure_logging
from app.review.flags import flag_source_drop
from app.sources.aa_world_services import AaWorldServicesDiscovery
from app.sources.ca_world_services import CaWorldServicesDiscovery
from app.sources.na_world_services import NaWorldServicesDiscovery
from app.sources.registry import (
    AdapterType,
    Source,
    SourceCandidate,
    SourceType,
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


if __name__ == "__main__":
    main()

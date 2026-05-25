# CA Completion Audit

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document follows `PLANS.md` in the repository root.

## Purpose / Big Picture

This pass answers whether Cocaine Anonymous (CA) ingestion has had the same completion check already applied to Narcotics Anonymous (NA). A completion check means counting active CA meetings, finding CA source registry rows that still have no active meetings, probing those source sites for recoverable meeting content, retrying the recoverable ones, and exporting a fresh snapshot when the database changes. The user-visible outcome is a documented CA disposition: active meeting counts, unrecovered source reasons, and a refreshed `snapshots/latest.json` if new CA meetings are recovered.

## Progress

- [x] (2026-05-25T12:03:10Z) Confirmed the worktree was clean on `main...origin/main` before starting.
- [x] (2026-05-25T12:03:10Z) Recorded the starting CA baseline: 2,336 active CA meetings, 79 active CA sources, 123 total CA sources, 44 zero-active CA sources, 21 zero-active `playwright_browser` sources, and 23 zero-active `unknown` sources.
- [x] (2026-05-25T12:03:10Z) Ran `audit-zero-sources --fellowship ca` against 21 zero-active browser sources. The audit produced 8 curated retry candidates.
- [x] (2026-05-25T12:05:00Z) Confirmed the 23 zero-active `unknown` CA rows are all CA world-service listing pages, and all 23 are shadowed by local source rows through `_ca_world_listings_shadowed_by_local_sources`.
- [x] (2026-05-25T12:07:00Z) Retried all 8 curated browser candidates with `scrape-all --fellowship ca --no-dry-run --concurrency 6 --max-pages-per-source 8`.
- [x] (2026-05-25T12:08:01Z) Exported a fresh snapshot after New Jersey recovery increased CA from 2,336 to 2,361 active meetings.
- [x] (2026-05-25T13:18:05+01:00) Imported the refreshed snapshot into the SoberSpace backend after a successful dry-run import.
- [ ] Commit and push the final audit documentation.

## Surprises & Discoveries

- Observation: `audit-zero-sources` only targets sources with `adapter_type = 'playwright_browser'` and zero active canonical meetings.
  Evidence: `app/cli.py` function `_zero_active_browser_sources` filters by `AdapterType.PLAYWRIGHT_BROWSER`, so CA's 23 `unknown` zero-active rows need separate handling.

- Observation: The 23 zero-active CA `unknown` rows are not missing local scrape work. They are CA world-service listing pages, and all 23 are shadowed by local CA source rows.
  Evidence: Running `_ca_world_listings_shadowed_by_local_sources` across all CA sources returned `shadowed_world_listing_count 23`, and each zero-active world listing printed as `shadowed`.

- Observation: The curated retry recovered only New Jersey.
  Evidence: `scrape-all` persisted `stored=25 canonical=25` for `ca-07c6c8d379bd`. The other 7 curated retry sources completed successfully with zero extracted records and no review flags.

## Decision Log

- Decision: Treat zero-active browser sources and zero-active unknown sources as separate CA audit buckets.
  Rationale: The existing zero-source audit command can produce high-quality live-probe classifications for browser sources, while unknown sources may be feed/PDF/phone/non-source rows and should not be silently ignored.
  Date/Author: 2026-05-25 / Codex.

- Decision: Reuse the existing scrape/audit/export CLI instead of adding new audit infrastructure first.
  Rationale: The repository already has commands for source probing, scraping, artifact import, and snapshot export. A narrow CA completion pass should prefer those paths unless the audit exposes a concrete parser or adapter bug.
  Date/Author: 2026-05-25 / Codex.

- Decision: Do not scrape the 23 CA world-service listing rows directly as part of this pass.
  Rationale: In a full CA scrape, `_ca_world_listings_shadowed_by_local_sources` skips world listings whose CA world-service URL already produced local source rows. All 23 zero-active unknown rows are in that intentionally shadowed category, so retrying them would duplicate or bypass the local-source-first policy.
  Date/Author: 2026-05-25 / Codex.

- Decision: Export and downstream-import a new snapshot after the CA retry.
  Rationale: The retry added 25 active CA meetings, there were no open CA error flags, and the previous NA completion workflow also validated and imported the latest snapshot into SoberSpace.
  Date/Author: 2026-05-25 / Codex.

## Outcomes & Retrospective

The CA completion audit recovered 25 additional active CA meetings from New Jersey. CA now has 2,361 active meetings across 80 active source rows. The remaining zero-active CA source rows are 20 browser sources that either had zero extracted records on retry or were lower-priority blocked/low-signal/manual cases, plus 23 intentionally shadowed CA world-service listing rows. There are zero open CA review flags.

The refreshed snapshot is `snapshots/meetings-2026-05-25T120801Z.json`, and `snapshots/latest.json` points at the same content. The snapshot contains 173,269 total meetings: 96,583 AA, 2,361 CA, and 74,325 NA. The SoberSpace backend dry run and committed import both used SHA-256 `e1acb23d11b25c991053264f75fc79996d100079e44627264ccb6fad13927eae`; the committed import run was `08dce78d-16d2-4fbd-a220-a2edc74cd841`.

## Context and Orientation

The repository stores recovery meeting source rows in `sources`, raw scrape records in `raw_meetings`, normalized public records in `canonical_meetings`, and review state in `review_flags`. A source is a local or world-service website that might publish meetings. A source with zero active meetings is a registry row for which `canonical_meetings` currently has no active CA records.

The main command module is `app/cli.py`. The command `scrape-all` visits source sites and can persist scrape results when run with `--no-dry-run`. The command `audit-zero-sources` probes zero-active browser sources and writes Markdown and text files under `scrape_artifacts/`, including a retry list for sources likely worth scraping again. The command `classify-sources` inspects unknown sources for feed-style integrations, but `docs/source_registry.md` says it is a legacy inspection path and not the default browser-scrape workflow. The command `export-snapshot --no-dry-run` writes a timestamped JSON snapshot and updates `snapshots/latest.json`.

The starting CA database state on 2026-05-25 was:

- Active CA canonical meetings: 2,336.
- CA sources with active meetings: 79.
- Total CA sources: 123.
- Zero-active CA sources: 44.
- CA source adapters: 100 `playwright_browser`, 23 `unknown`.
- Zero-active CA sources by adapter: 21 `playwright_browser`, 23 `unknown`.
- Open CA review flags: 0.
- Latest snapshot before this pass: `snapshots/meetings-2026-05-25T113118Z.json`, with `ca = 2,336`, `na = 74,325`, and `aa = 96,583`.

The ending CA database state after retry and export was:

- Active CA canonical meetings: 2,361.
- CA sources with active meetings: 80.
- Total CA sources: 123.
- Zero-active CA sources: 43.
- Zero-active CA sources by adapter: 20 `playwright_browser`, 23 `unknown`.
- Open CA review flags: 0.
- Latest snapshot after this pass: `snapshots/meetings-2026-05-25T120801Z.json`, with `ca = 2,361`, `na = 74,325`, and `aa = 96,583`.

## Plan of Work

First, run `audit-zero-sources --fellowship ca` into a timestamped artifact directory. Review `summary.md`, bucket counts, and `retry-source-ids.txt`. The retry list is the first candidate set for recoverable CA browser sources.

Second, list the 23 zero-active CA `unknown` rows from the database with source id, name, URL, country, region, and existing classification config. Run `classify-sources --fellowship ca --retry-classified-unknown --concurrency 8` as a dry run or targeted live inspection for these rows if they lack useful metadata. Persist classification only when the result clearly improves the registry and does not overwrite valid user-maintained configuration.

Third, retry recoverable sources concurrently with `scrape-all --fellowship ca --no-dry-run --source-id ... --concurrency 6 --max-pages-per-source 8`. The retry should use the source ids from the zero-source audit plus any unknown sources that become scrapeable. Each successful scrape should persist raw records, canonical candidates, and updated review flags through the normal `scrape-all` path.

Fourth, validate database counts after retries. If active CA meetings increase or source coverage changes, run `export-snapshot --no-dry-run` and record the new snapshot path. If the snapshot changes, import it into the SoberSpace backend only after confirming the ingestion snapshot has no open error flags.

Fifth, update this ExecPlan and any CA audit documentation with final counts and unrecovered reasons. Commit and push only after validation passes and generated artifacts/docs are in the desired state.

## Concrete Steps

All commands are run from `/home/michaelroddy/repos/recovery-meeting-ingestion` unless stated otherwise.

Run the zero-active browser audit:

    PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers .venv/bin/python -m app.cli audit-zero-sources --fellowship ca --output-dir scrape_artifacts/ca-zero-source-audit-20260525T120310Z --concurrency 16 --retry-concurrency 6 --retry-max-pages 8

The command reported:

    Zero-source audit fellowship=ca
    sources: 21
    curated_retry_sources: 8
    - blocked_or_captcha: 4
    - low_signal: 4
    - parser_gap_candidate: 3
    - possible_missed_structured_feed: 3
    - meeting_keywords_only: 3
    - dead_or_error_page: 2
    - possible_pdf_or_printable: 1
    - possible_embed_or_calendar: 1

List zero-active CA sources by adapter:

    .venv/bin/python - <<'PY'
    from psycopg.rows import dict_row
    from app.config import get_settings
    from app.storage.database import connect
    settings = get_settings()
    with connect(settings) as connection, connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("""
            SELECT s.id, s.name, s.url, s.country, s.region, s.adapter_type, s.config
            FROM sources s
            LEFT JOIN (
                SELECT source_id, COUNT(*) AS active_count
                FROM canonical_meetings
                WHERE fellowship = 'ca' AND status = 'active'
                GROUP BY source_id
            ) cm ON cm.source_id = s.id
            WHERE s.fellowship = 'ca' AND COALESCE(cm.active_count, 0) = 0
            ORDER BY s.adapter_type, s.country NULLS LAST, s.name
        """)
        for row in cursor.fetchall():
            print(row)
    PY

Retry recoverable sources after reviewing the audit output:

    PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers .venv/bin/python -m app.cli scrape-all --fellowship ca --no-dry-run --concurrency 6 --max-pages-per-source 8 --output-dir scrape_artifacts/ca-curated-zero-retry-20260525T120310Z --source-id ca-200708853eaf --source-id ca-d7d0c4eae08f --source-id ca-f6c1ff14a8cb --source-id ca-f60993c27baf --source-id ca-07c6c8d379bd --source-id ca-c96cd333bd23 --source-id ca-e4d3d7f0476f --source-id ca-609577b509b9

The retry results were:

    ca-07c6c8d379bd succeeded pages=5 extracted=25 stored=25 canonical=25
    ca-200708853eaf succeeded pages=1 extracted=0 stored=0 canonical=0
    ca-609577b509b9 succeeded pages=8 extracted=0 stored=0 canonical=0
    ca-c96cd333bd23 succeeded pages=1 extracted=0 stored=0 canonical=0
    ca-d7d0c4eae08f succeeded pages=1 extracted=0 stored=0 canonical=0
    ca-e4d3d7f0476f succeeded pages=2 extracted=0 stored=0 canonical=0
    ca-f60993c27baf succeeded pages=3 extracted=0 stored=0 canonical=0
    ca-f6c1ff14a8cb succeeded pages=1 extracted=0 stored=0 canonical=0

Export a fresh snapshot if CA meeting counts change:

    .venv/bin/python -m app.cli export-snapshot --no-dry-run

The export reported:

    Snapshot export
    active_meetings: 173269
    stale_meetings: 0
    blocked_by_review: 0
    output: snapshots/meetings-2026-05-25T120801Z.json
    snapshot_id: eede1afc-2b7d-4312-9dae-d81500730c1b

Validate and import the snapshot in the SoberSpace backend from `/home/michaelroddy/repos/project_radeon`:

    GOCACHE=/tmp/go-build GOMODCACHE=/tmp/go-mod go run ./cmd/import-recovery-meetings --snapshot /home/michaelroddy/repos/recovery-meeting-ingestion/snapshots/latest.json --dry-run
    GOCACHE=/tmp/go-build GOMODCACHE=/tmp/go-mod go run ./cmd/import-recovery-meetings --snapshot /home/michaelroddy/repos/recovery-meeting-ingestion/snapshots/latest.json

The committed import reported:

    Recovery meeting import committed
    Import run: 08dce78d-16d2-4fbd-a220-a2edc74cd841
    Snapshot SHA-256: e1acb23d11b25c991053264f75fc79996d100079e44627264ccb6fad13927eae
    Meetings seen: 173269
    Meetings upserted: 173269
    Occurrences written: 162352
    Marked stale: 858
    Marked inactive: 0

## Validation and Acceptance

Acceptance requires a final report that includes active CA meeting count, CA source coverage, zero-active source count by adapter, audit bucket counts, retry source ids, and any changed snapshot path. The database should have zero open CA error review flags before any final snapshot is considered publishable. If new meetings are recovered, `export-snapshot --no-dry-run` should report the increased active meeting count and write a new timestamped snapshot plus `snapshots/latest.json`.

Run the focused test suite before committing code changes if this pass edits parser, scraper, or CLI code:

    .venv/bin/python -m pytest tests/test_cli.py tests/test_zero_source_audit.py tests/test_scraping_service.py

No code changes were made in this pass, so validation is the CLI audit/retry/export transcripts, database count queries, snapshot count inspection, and the SoberSpace dry-run plus committed import.

## Idempotence and Recovery

The audit command writes files and does not mutate source or meeting records. It is safe to rerun into a new timestamped directory. `scrape-all --no-dry-run` is designed to upsert raw and canonical records by source and source record id, then mark missing records for that source, so retries should be limited to audited source ids rather than all CA sources. If a retry unexpectedly drops many meetings for a source, review the generated source-drop review flag before exporting a snapshot.

## Artifacts and Notes

Planned artifact directories:

- `scrape_artifacts/ca-zero-source-audit-20260525T120310Z`
- `scrape_artifacts/ca-curated-zero-retry-20260525T120310Z`

Revision note: Created this ExecPlan to convert the CA comparison question into a concrete, restartable completion audit and recovery pass.

Revision note: Updated the ExecPlan with final CA audit counts, retry evidence, snapshot export details, and downstream import results.

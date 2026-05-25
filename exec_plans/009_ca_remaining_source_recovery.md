# CA Remaining Source Recovery

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document follows `PLANS.md` in the repository root.

## Purpose / Big Picture

This pass drives CA source coverage as close to complete as the available source registry allows. After `exec_plans/008_ca_completion_audit.md`, CA had 2,361 active meetings across 80 active sources, but 20 local CA source rows still had no active meetings. This plan inspects those 20 local sources, adds targeted scraper or parser support where meeting data is available, retries the fixed sources, exports a refreshed combined AA/CA/NA snapshot, imports it into SoberSpace, and records a final disposition for every source that still cannot produce meetings.

## Progress

- [x] (2026-05-25T12:23:26Z) Confirmed the worktree was clean on `main...origin/main` before starting.
- [x] (2026-05-25T12:23:26Z) Confirmed the remaining actionable CA gaps were 20 `local_service_body` sources with `playwright_browser` adapters and zero active meetings.
- [x] (2026-05-25T12:35:00Z) Inspected all 20 remaining local CA sources concurrently and classified 10 as recoverable with source-specific parsing.
- [x] (2026-05-25T12:50:00Z) Added `app/scraping/ca_source_specific.py`, wired it into `app/scraping/service.py`, and added focused tests in `tests/test_ca_source_specific.py`.
- [x] (2026-05-25T12:52:00Z) Retried the 10 recoverable CA sources and persisted new records. Wisconsin initially created 4 normalization errors, then a parser fix and rerun cleared them.
- [x] (2026-05-25T12:56:15Z) Exported `snapshots/meetings-2026-05-25T125615Z.json` after CA increased to 2,575 active meetings.
- [x] (2026-05-25T14:06:24+01:00) Dry-run validated and committed the refreshed snapshot into the SoberSpace backend.
- [x] (2026-05-25T14:06:24+01:00) Documented final source dispositions, validation evidence, and remaining unrecoverable sources.
- [ ] Commit and push code/documentation changes.

## Surprises & Discoveries

- Observation: The repository had an established source-specific direct-fetch pattern for NA in `app/scraping/na_source_specific.py`, but no CA equivalent.
  Evidence: `app/scraping/service.py` called `fetch_source_specific_na_records` before falling back to `BrowserCrawler`; this pass added a matching `fetch_source_specific_ca_records` path.

- Observation: Several CA sources had usable meeting data that the generic root-page browser crawl missed.
  Evidence: Direct inspection recovered Maritimes online cards, Quebec tables, Denmark tables, Greece online schedule text, Russia daily group text, Oklahoma static schedule text, Wisconsin line schedule text, Nashville day blocks, Columbus day blocks, and Texas Houston time blocks.

- Observation: Generic extraction can under-extract or over-combine long line schedules.
  Evidence: Texas previously produced only a few broad records through generic extraction, while the source-specific time-block parser produced 44 normalized meetings from the same public page.

## Decision Log

- Decision: Treat the 20 zero-active CA local sources as the recovery target and exclude the 23 zero-active CA world-service listing rows from this pass.
  Rationale: `exec_plans/008_ca_completion_audit.md` proved the 23 unknown rows are CA world-service listing pages shadowed by local sources. They are registry placeholders, not independent local scrape targets under the current CA strategy.
  Date/Author: 2026-05-25 / Codex.

- Decision: Add a CA source-specific module instead of expanding NA-specific code or only tuning generic extraction.
  Rationale: CA recovery needed distinct source ids, URLs, language handling, and parser functions. Keeping this in `app/scraping/ca_source_specific.py` mirrors the NA pattern without mixing fellowship-specific behavior.
  Date/Author: 2026-05-25 / Codex.

- Decision: Prefer targeted direct-fetch/source-specific code only when a site inspection revealed stable public meeting data.
  Rationale: The generic browser crawler remains the default. Source-specific code is justified for stable one-off tables, line schedules, embedded calendars, PDFs, and unusual markup that the generic extraction path cannot reliably normalize.
  Date/Author: 2026-05-25 / Codex.

## Outcomes & Retrospective

The remaining-source recovery pass added 214 active CA meetings and 10 active CA sources. CA moved from 2,361 active meetings across 80 active sources to 2,575 active meetings across 90 active sources. The combined snapshot now has 173,483 meetings: 96,583 AA, 2,575 CA, and 74,325 NA.

The remaining local CA gaps are 10 sources: Hong Kong timed out, Netherlands/Indiana/San Diego returned a network parental-control block page, CyberSerenity did not publish a dated weekly meeting schedule, Central UK rendered a loading shell with no extractable schedule, Connecticut published no meeting list on its page, Maine and North Texas failed DNS lookup, and SFVCA uses an Airtable embed whose public HTML/API did not expose records to the scraper. The 23 zero-active `unknown` rows remain shadowed CA world-service listing placeholders, not independent local scrape targets.

The refreshed snapshot was dry-run validated and imported into SoberSpace. The committed import run was `fe803b9e-d3e1-4c87-8ce7-d141870f0347`, with SHA-256 `597268fbbac50fbe81a86408e56f22b893be09047210a71b8fab699b5aaaff58`, 173,483 meetings seen/upserted, 162,572 occurrences written, 0 marked stale, and 858 marked inactive.

## Context and Orientation

The repository stores source rows in `sources`, raw scrape output in `raw_meetings`, normalized public records in `canonical_meetings`, and review status in `review_flags`. The main scrape entry point is `app/scraping/service.py`. It tries direct source-specific fetchers first, then falls back to `BrowserCrawler`. This pass added a CA-specific direct fetcher in `app/scraping/ca_source_specific.py`.

The recovered CA source counts were:

- `ca-f60993c27baf` Quebec: 84 active meetings.
- `ca-f6c1ff14a8cb` Texas: 44 active meetings.
- `ca-63a0c6bbe7d2` Denmark: 25 active meetings.
- `ca-e4d3d7f0476f` Wisconsin: 20 active meetings.
- `ca-200708853eaf` Nashville: 10 active meetings.
- `ca-d7d0c4eae08f` Columbus: 9 active meetings.
- `ca-2915b40b65f2` Greece: 8 active meetings.
- `ca-60973398a3f3` Oklahoma: 7 active meetings.
- `ca-4b3b7087b949` Maritimes: 6 active meetings.
- `ca-e2f77889edc7` Russia: 1 active meeting.

The remaining local CA source dispositions were:

- `ca-35a80b91e362` Hong Kong, `http://cahongkong.com/`: live request timed out from this environment.
- `ca-323a95f13ea7` Netherlands, `http://ca-holland.org/`: returned a network parental-control block page.
- `ca-515a0089a544` CyberSerenity, `https://cyberserenity.org`: site is live, but no dated weekly meeting schedule was found.
- `ca-609577b509b9` Central UK, `http://centralukca.co.uk`: rendered only a loading shell and generic retry found no extractable schedule.
- `ca-041da33d75c7` Connecticut, `http://www.caofct.org/`: site is live, but no public meeting list was found.
- `ca-02679930ead3` Indiana, `http://www.indiana-ca.org/`: returned a network parental-control block page.
- `ca-e2760999c192` Maine old Webs site, `http://camaine-com.webs.com/`: DNS lookup failed.
- `ca-a881e4c39ef0` San Diego, `http://www.casandiego.org/`: returned a network parental-control block page.
- `ca-c96cd333bd23` SFVCA, `http://www.sfvca.org/`: site embeds an Airtable directory, but public HTML/API access did not expose meeting rows.
- `ca-23b0bd1f769e` North Texas, `http://www.northtexasca.com/`: DNS lookup failed.

## Plan of Work

First, inspect the latest artifact directories and live source pages for all 20 remaining local sources. For each source, record whether a public meeting schedule exists, whether it is HTML, PDF, feed/API, calendar, embedded widget, blocked, dead, obsolete, or duplicate.

Second, implement the smallest targeted recovery for any source that has stable public meeting data. Prefer source-specific direct fetchers for APIs, static PDFs, and odd but stable HTML. Prefer source config changes only when the generic browser crawler already supports the site but needs a better URL or action.

Third, add focused tests for parser functions and service routing changed in this pass. Run the relevant unit tests plus a live retry of the affected source ids.

Fourth, persist recovered records with `scrape-all --fellowship ca --no-dry-run`, export a fresh snapshot because CA active counts increased, and import the snapshot into SoberSpace after dry-run validation.

Fifth, update this plan and a documentation note with final source dispositions.

## Concrete Steps

All commands run from `/home/michaelroddy/repos/recovery-meeting-ingestion` unless stated otherwise.

The main retry command was:

    PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers .venv/bin/python -m app.cli scrape-all --fellowship ca --no-dry-run --concurrency 6 --max-pages-per-source 12 --output-dir scrape_artifacts/ca-source-recovery-retry-20260525T122326Z --source-id ca-4b3b7087b949 --source-id ca-f60993c27baf --source-id ca-63a0c6bbe7d2 --source-id ca-2915b40b65f2 --source-id ca-e2f77889edc7 --source-id ca-60973398a3f3 --source-id ca-e4d3d7f0476f --source-id ca-200708853eaf --source-id ca-d7d0c4eae08f --source-id ca-f6c1ff14a8cb

The Wisconsin cleanup rerun was:

    PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers .venv/bin/python -m app.cli scrape-all --fellowship ca --no-dry-run --concurrency 1 --max-pages-per-source 12 --output-dir scrape_artifacts/ca-source-recovery-retry-20260525T122326Z-rerun --source-id ca-e4d3d7f0476f

The final database state before export was:

    active_meetings: 2575
    active_sources: 90
    total_sources: 123
    open_flags: 0
    open_errors: 0

The snapshot export command was:

    .venv/bin/python -m app.cli export-snapshot --no-dry-run

The export reported:

    Snapshot export
    active_meetings: 173483
    stale_meetings: 0
    blocked_by_review: 0
    output: snapshots/meetings-2026-05-25T125615Z.json
    snapshot_id: 042cab9e-4560-41d2-bcf8-2fe8565b4ee4

The downstream import validation from `/home/michaelroddy/repos/project_radeon` was:

    GOCACHE=/tmp/go-build GOMODCACHE=/tmp/go-mod go run ./cmd/import-recovery-meetings --snapshot /home/michaelroddy/repos/recovery-meeting-ingestion/snapshots/latest.json --dry-run
    GOCACHE=/tmp/go-build GOMODCACHE=/tmp/go-mod go run ./cmd/import-recovery-meetings --snapshot /home/michaelroddy/repos/recovery-meeting-ingestion/snapshots/latest.json

The committed import reported:

    Recovery meeting import committed
    Import run: fe803b9e-d3e1-4c87-8ce7-d141870f0347
    Snapshot SHA-256: 597268fbbac50fbe81a86408e56f22b893be09047210a71b8fab699b5aaaff58
    Meetings seen: 173483
    Meetings upserted: 173483
    Occurrences written: 162572
    Marked stale: 0
    Marked inactive: 858

## Validation and Acceptance

Acceptance requires every one of the 20 remaining local CA source rows to have either active canonical CA meetings or a documented final disposition explaining why it cannot currently produce meetings. Any parser or service routing code added in this pass must have focused tests. If new meetings are recovered, the final snapshot must contain the increased CA count and the SoberSpace backend import must succeed.

Validation completed:

    .venv/bin/python -m pytest tests/test_ca_source_specific.py tests/test_scraping_service.py tests/test_cli.py
    35 passed

The database had 2,575 active CA meetings, 90 active CA sources, and zero open CA review flags before snapshot export. The combined snapshot and downstream import both succeeded.

## Idempotence and Recovery

Source inspection is read-only except for generated artifacts. `scrape-all --no-dry-run` should be limited to source ids from this pass so a failed parser does not affect unrelated CA sources. Snapshot export should only be run after confirming open error review flags are zero. If downstream dry-run import fails, do not run the committed import; record the failure in this plan.

For routine full refreshes, scrape jobs can be run per fellowship:

    PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers .venv/bin/python -m app.cli scrape-all --fellowship aa --no-dry-run --concurrency 6
    PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers .venv/bin/python -m app.cli scrape-all --fellowship ca --no-dry-run --concurrency 6
    PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers .venv/bin/python -m app.cli scrape-all --fellowship na --no-dry-run --concurrency 6

Then run one global `export-snapshot --no-dry-run`. On a successful source scrape, additions are upserted and previously active meetings from that same source that are no longer present are marked missing/stale. If a source is blocked, dead, or parser-broken, avoid treating a zero-record scrape as a real deletion without review.

## Artifacts and Notes

Artifact directories used:

- `scrape_artifacts/ca-source-recovery-retry-20260525T122326Z`
- `scrape_artifacts/ca-source-recovery-retry-20260525T122326Z-rerun`

Revision note: Created this ExecPlan to pursue complete CA local-source coverage after the CA completion audit left 20 zero-active local sources.

Revision note: Updated the plan with implementation details, final recovery counts, remaining source dispositions, snapshot export evidence, downstream import evidence, validation results, and the routine full-refresh behavior.

# AA Source Discovery And Scrape Coverage

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This file follows `PLANS.md` in this repository.

## Purpose / Big Picture

SoberSpace already imports reviewed recovery meeting snapshots, but the current snapshot contains very little Alcoholics Anonymous coverage compared with CA and NA. After this work, the ingestion database should contain a much larger, reviewed AA meeting set from local A.A. office and intergroup websites. The result is visible by exporting `snapshots/latest.json` and checking that AA meeting counts increase, then importing that snapshot into the SoberSpace backend.

The work is operational and iterative. AA source discovery already exists in `app/sources/aa_world_services.py`, and browser-first scraping already exists in `app/scraping/`. The main task is to run AA discovery, scrape controlled batches, inspect failed or zero-result sites, fix common scraper gaps when they appear, run the full AA scrape/import, and export a new snapshot.

## Progress

- [x] (2026-05-23T23:50+01:00) Confirmed worktree is clean on `main`.
- [x] (2026-05-23T23:52+01:00) Baseline database state: `sources` has 1,107 AA rows, `canonical_meetings` has 114 AA rows, and review flags for AA are 0 errors and 20 warnings.
- [x] (2026-05-23T23:53+01:00) Created this ExecPlan for the AA scrape pass.
- [x] (2026-05-24T00:03+01:00) Ran AA discovery dry-run; it found 1,107 candidates, matching the existing AA source registry count.
- [x] (2026-05-24T00:10+01:00) Ran persisted AA discovery; it reported 1,107 stored sources.
- [x] (2026-05-24T00:16+01:00) Fixed `SourceRepository.upsert_source` so rediscovery cannot downgrade configured adapters to `unknown`, added a DB regression test, and restored the 8 AA artifact-import sources to `playwright_browser`.
- [x] (2026-05-24T00:25+01:00) Ran a controlled AA scrape batch of 20 scrapeable sources with local Playwright browser binaries; all 20 completed, 8 produced records, 12 produced zero records, and 2,965 raw records were extracted.
- [x] (2026-05-24T00:31+01:00) Fixed truncated Spanish weekday normalization after the Costa Rica source produced 224 normalization errors.
- [x] (2026-05-24T00:38+01:00) Added country/region timezone inference for static/browser-normalized rows, including Australia state abbreviations and Costa Rica.
- [x] (2026-05-24T00:47+01:00) Added AA-specific search/list discovery targets for `meeting`, `find a meeting`, `groups`, `AA groups`, and `meeting locations`; broadened heuristic form submission seeds; added a hard per-page browser timeout; and added `scrape-all --offset` for safer resume batches.
- [x] (2026-05-24T01:28+01:00) Added frame text capture and rendered-column extraction for AA search result pages where visible rows are inside Wix/embedded frames. A dry-run of `aa-d9b59e67bf51` improved from 0 extracted records to 50 extracted records and 25 normalized candidates.
- [x] (2026-05-24T02:00+01:00) Added scrape metadata persistence so failed browser scrapes set `config.scrape.last_status=failed` and are skipped by future `scrape-all` runs unless `--include-failed` is passed. Added the same metadata backfill to `import-artifacts --no-dry-run`, and added a stop condition for empty high-confidence meeting/search pages so the crawler does not continue into unrelated broad fallback links after finding the likely directory.
- [x] (2026-05-24T02:05+01:00) Added remembered successful page URLs for all browser-scraped fellowships. Live scrapes and artifact imports now persist `config.scrape.successful_pages`; future runs seed the crawler with those pages before falling back to source-root scanning.
- [x] (2026-05-24T10:03+01:00) Added a bounded `scrape-all --concurrency` option. The default remains serial, while operators can now run multiple source scrapes concurrently for AA, CA, NA, or all fellowships. Focused validation passed with `ruff`, `mypy`, and `tests/test_cli.py`.
- [x] (2026-05-24T10:49+01:00) Completed the full AA scrape/import resume. The offset 463 resume wrote `scrape_artifacts/aa-full-resume-20260524T092816Z` at concurrency 4 through progress 51/215, then the remaining batch resumed at offset 514 with concurrency 8 into `scrape_artifacts/aa-full-resume-20260524T093353Z` and completed 164/164. The concurrency-8 batch finished with 147 succeeded sources, 17 failed sources, 13,884 normalized candidates, and 9,317 review flags. Across all AA browser sources, 664 distinct AA sources now have import runs, and the database contains 94,394 active AA canonical meetings.
- [x] (2026-05-24T10:49+01:00) Audited AA review blockers and exported a new snapshot. The audit found two open AA `source_large_drop` errors: Northern Virginia Intergroup and the local fixture-style `aa-ie-feed`. Northern Virginia was restored by reimporting the successful artifact `scrape_artifacts/aa-full-resume-20260524T092816Z/aa-4f1f1cdaa6f9/summary.json`; the `aa-ie-feed` stale-source error was resolved because the source points at `https://example.org/meetings.json` and has no active meetings. `export-snapshot --no-dry-run` wrote `snapshots/meetings-2026-05-24T094908Z.json` and `snapshots/latest.json` with 99,416 active meetings total, including 94,394 AA meetings, and `blocked_by_review=0`.
- [x] (2026-05-24T10:49+01:00) Fixed failed-scrape persistence so a failed scrape records source metadata and a failed import run without replacing canonical meetings or review flags. Added a regression test proving failed scrapes do not mark existing meetings stale.
- [x] (2026-05-24T02:05+01:00) Ran validation after the latest scraper/resume changes: `.venv/bin/ruff check app tests`, `.venv/bin/pytest tests/test_cli.py tests/test_scraping_primitives.py tests/test_artifact_import.py -q`, `.venv/bin/mypy app`, and `.venv/bin/pytest -q` all passed.
- [x] (2026-05-24T10:49+01:00) Ran focused validation after the concurrency and failed-scrape persistence changes: `.venv/bin/ruff check app tests`, `.venv/bin/pytest tests/test_cli.py -q`, and `.venv/bin/mypy app` all passed.
- [x] (2026-05-24T10:56+01:00) Cleared the largest AA missing-timezone warning cluster. Canadian province abbreviation support and address-based Canada/province inference now let the Montreal Spanish intergroup TSML rows infer timezones from addresses such as `Saint-Jérôme, QC, Canada`. Reimporting `scrape_artifacts/aa-full-resume-20260524T093353Z/aa-fd84ea48efda/summary.json` reduced that source from 2,540 open warnings to 763 and reduced AA open warnings from 37,658 to 35,881. A refreshed snapshot was exported at `snapshots/meetings-2026-05-24T095621Z.json` with `blocked_by_review=0`.

## Surprises & Discoveries

- Observation: AA discovery has already populated many sources, but little AA canonical data exists.
    Evidence: `SELECT fellowship, COUNT(*) FROM sources GROUP BY fellowship` returned `aa=1107`, while `SELECT fellowship, COUNT(*) FROM canonical_meetings GROUP BY fellowship` returned `aa=114`.
- Observation: AA sources have no recorded scrape status yet.
    Evidence: `SELECT config->'scrape'->>'last_status', COUNT(*) FROM sources WHERE fellowship='aa' GROUP BY 1` returned one empty-status group with 1,107 rows.
- Observation: Most AA sources are local websites or phone rows.
    Evidence: Source type counts were 683 `local_service_body/unknown`, 415 `phone/manual_review`, 8 `local_service_body/playwright_browser`, and 1 `meeting_feed/meeting_guide`.
- Observation: Live AA discovery redirects several United Kingdom sub-options back to `cc=GB`.
    Evidence: Dry-run output showed `cc=GB1`, `cc=GB2`, `cc=GB3`, and `cc=GB4` returning HTTP 301 followed by HTTP 200 for `cc=GB`. The discovery client followed redirects and still completed successfully.
- Observation: Live AA discovery currently matches the existing source registry count.
    Evidence: `discover-sources --fellowship aa --dry-run` reported `candidates: 1107`, equal to the baseline AA source count.
- Observation: Persisted AA discovery exposed an adapter downgrade bug.
    Evidence: Before persisted discovery, AA source type counts included 8 `local_service_body/playwright_browser` rows. After persisted discovery, those rows became `local_service_body/unknown` while still carrying `config->scrape->artifact_import = true`. The upsert statement was replacing `adapter_type` with the rediscovered default `unknown`.
- Observation: AA browser scraping needs search/list targets more than CA-style static meeting tables.
    Evidence: The controlled and full runs showed many AA sites with zero rows despite successful page loads. User inspection confirmed many AA sites place meetings under search/filter experiences such as "find a meeting", "groups", "AA groups", or "meeting locations" rather than a direct list.
- Observation: The Costa Rica AA source used truncated Spanish weekday labels.
    Evidence: `aa-9b8419478223` extracted 226 raw records but only normalized 2 before the fix. Rows used labels such as `Lune`, `Marte`, `Miercole`, `Jueve`, and `Vierne`. After the normalizer fix, the same source normalized 226 candidates.
- Observation: Australia and Costa Rica missing-timezone warnings were fixable with country/region inference.
    Evidence: Before the timezone fix, AA open `missing_timezone` warnings were dominated by Australia and Costa Rica. After rerunning those sources, Costa Rica produced 0 review flags and Australia occurrences used `Australia/Sydney`, `Australia/Melbourne`, `Australia/Brisbane`, `Australia/Perth`, `Australia/Adelaide`, `Australia/Hobart`, and `Australia/Darwin`.
- Observation: Some correct AA meeting pages are Wix-rendered and still do not expose extractable rows.
    Evidence: A dry-run of `aa-d9b59e67bf51` visited `/meetings`, `/meetings/find-a-meeting`, `/groups`, and `/meeting-updates`; the pages scored as meeting pages but extracted 0 records. The rendered artifact is a Wix page with no visible meeting row text in the saved HTML.
- Observation: Some visible AA result tables are rendered inside iframes.
    Evidence: The `aa-d9b59e67bf51` screenshot showed a meeting table, but the main frame body text omitted it. Inspecting page frames showed the table under `www-aanc24-org.filesusr.com/html/...`; collecting all frame body text and parsing tabbed column rows extracted 50 records.
- Observation: The first full AA scrape could not be interactively stopped through the existing tool session.
    Evidence: Polling session `75383` still returns new scrape output, but sending Ctrl-C fails with `stdin is closed`, and `pgrep` from a fresh command only sees the new command wrapper rather than the original scrape process. Artifact and database checkpoints are therefore the reliable recovery markers.
- Observation: `--offset` is sensitive to status filtering.
    Evidence: `scrape-all` filters previously failed sources before applying `_select_scrape_batch`. During the concurrency switch, the first resumed run reached progress 51/215, then the next run used offset 514. Because some earlier sources had become failed and were excluded from the second source list, the offset boundary drifted. The final database still shows import runs for all 664 AA browser sources, but future interrupted resumes should prefer artifact/source-id checkpoints over relying only on a numeric offset after the source status set has changed.
- Observation: Failed browser scrapes were able to stale out existing meetings.
    Evidence: `aa-4f1f1cdaa6f9` first imported 576 Northern Virginia meetings from `https://nvintergroup.org/feed/json`, then a later failed scrape persisted zero candidates and created an open `source_large_drop` error while marking the 576 meetings `stale`. The fix now treats failed scrape persistence as metadata-only for canonical meeting data.
- Observation: Open AA review errors were cleared before export, but many warnings remain for later quality work.
    Evidence: After resolving the two open `source_large_drop` errors, `export-snapshot --dry-run` reported `blocked_by_review: 0`. The remaining AA open warnings totaled 37,658 and were dominated by `possible_personal_contact`, `possible_private_online_credential`, and one high-volume `missing_timezone` source, `aa-fd84ea48efda`.
- Observation: The Montreal Spanish intergroup feed covers Quebec plus a few New Brunswick and Nunavut rows.
    Evidence: After address-based Canada/province inference, `aa-fd84ea48efda` occurrences used `America/Toronto` for 1,765 rows, `America/Moncton` for 11 New Brunswick rows, and `America/Iqaluit` for one Iqaluit row. The source no longer has open `missing_timezone` warnings.

## Decision Log

- Decision: Use controlled AA scrape batches before running all AA sources.
    Rationale: More than 600 AA web sources are scrapeable. Running all of them immediately would produce a large, slow batch with less useful debugging feedback. A controlled batch reveals common extraction failures first.
    Date/Author: 2026-05-23 / Codex.
- Decision: Keep phone-only AA rows out of automated scraping.
    Rationale: The existing `scrape-all` path excludes `SourceType.PHONE`, which is appropriate because phone rows require manual contact or a separate manual-review workflow rather than browser scraping.
    Date/Author: 2026-05-23 / Codex.
- Decision: Preserve configured source adapter metadata during discovery upserts.
    Rationale: Discovery should refresh source labels, URLs, regions, and metadata, but it should not erase source-specific scraper configuration learned from previous artifact imports or classification. The code now preserves an existing non-`unknown` adapter when the incoming discovered source adapter is `unknown`.
    Date/Author: 2026-05-24 / Codex.
- Decision: Treat `groups`, `AA groups`, and `meeting locations` as meeting directory routes.
    Rationale: AA local sites commonly use group/location terminology for public meeting directories. These routes should be prioritized alongside `meetings` and `find a meeting` while service/admin pages remain negatively scored.
    Date/Author: 2026-05-24 / Codex.
- Decision: Add a scrape batch offset option.
    Rationale: AA has hundreds of scrapeable web sources. `--offset` lets production or local operators resume in bounded chunks after a stalled or interrupted batch instead of always restarting at the beginning.
    Date/Author: 2026-05-24 / Codex.
- Decision: Include iframe body text in rendered-text extraction.
    Rationale: Wix and embedded meeting widgets can render the visible meeting list in child frames. Capturing all frame text lets the existing browser pass normalize visible results without source-specific selectors.
    Date/Author: 2026-05-24 / Codex.
- Decision: Persist scrape outcome metadata on the source row.
    Rationale: `scrape-all` already knows how to skip sources with previous `failed` scrape status, but that status was not written after browser scrapes. Writing pages visited, records extracted, artifact path, and error text makes retries resumable and prevents repeated DNS/SSL/dead-site work unless `--include-failed` is explicit. `import-artifacts --no-dry-run` writes the same metadata from artifact summaries so older interrupted runs can be backfilled.
    Date/Author: 2026-05-24 / Codex.
- Decision: Stop after an empty high-confidence meeting directory page.
    Rationale: AA sites often have a single search/filter page. If the crawler reaches a strong `find a meeting`/groups/location page and extracts nothing after interactions, broad fallback links are more likely to waste pages than find meetings. Landing pages are excluded from this stop rule so discovery can still reach deeper directories.
    Date/Author: 2026-05-24 / Codex.
- Decision: Remember successful meeting pages per source.
    Rationale: Repeat scrapes should not have to rediscover known meeting directories. Successful browser pages are stored in `sources.config.scrape.successful_pages` with URL, extracted record count, score, and signals. The crawler tries those remembered URLs first for AA, CA, NA, and any future browser-scraped fellowship, then falls back to normal source-root and common-path scanning if the remembered pages are stale or empty.
    Date/Author: 2026-05-24 / Codex.
- Decision: Add bounded source-level concurrency to `scrape-all` rather than parallelizing pages inside a source.
    Rationale: Source-level concurrency is the smallest change that improves full-pass scrape time across AA, CA, and NA while preserving each crawler's per-source page ordering, artifact layout, and timeout behavior. Database persistence remains bounded so concurrent browser work does not create avoidable write contention.
    Date/Author: 2026-05-24 / Codex.
- Decision: Persist failed scrapes without replacing canonical meetings or review flags.
    Rationale: A failed browser run indicates that the source could not be checked, not that all previously known meetings disappeared. Source scrape metadata and a failed import run are still useful evidence, but canonical rows and source review flags should only be replaced by a successful scrape or artifact import.
    Date/Author: 2026-05-24 / Codex.
- Decision: Resolve the `aa-ie-feed` large-drop error instead of reactivating its fixture meetings.
    Rationale: `aa-ie-feed` is a local fixture-style source with URL `https://example.org/meetings.json`, not a real AA source. Its two canonical rows were already stale and should not be reintroduced into the public snapshot. Resolving its stale-source error unblocked export without adding fake active meetings.
    Date/Author: 2026-05-24 / Codex.
- Decision: Infer Canadian timezones from address province abbreviations for static/browser-normalized rows.
    Rationale: TSML JSON and rendered rows often include a full postal address but no explicit source country or timezone. Province abbreviations such as `QC`, `NB`, and `NU` are enough to choose a canonical timezone without source-specific configuration, and this also handles multi-province feeds correctly.
    Date/Author: 2026-05-24 / Codex.

## Outcomes & Retrospective

The controlled AA scrape proved the browser path can ingest AA meetings at meaningful scale: AA canonical meetings increased from 114 to more than 3,000 after controlled source reruns and the first part of the full pass. The main remaining risk is not browser availability, but hidden/search-backed local meeting directories. The current code now targets AA search/list route names and form patterns directly, but Wix-style meeting pages may still need a dedicated data extractor in a later pass.

The full AA pass has now completed and produced a publishable snapshot. `snapshots/latest.json` contains 94,394 AA meetings, up from the baseline of 114, with 99,416 active meetings total across AA, CA, and NA. The snapshot is not blocked by open error flags. The largest missing-timezone cluster has been cleared. The main remaining quality work is warning reduction for contact/online credential warnings that may be false positives for legitimate group phone numbers or meeting passwords.

## Context and Orientation

This repository is `/home/michaelroddy/repos/recovery-meeting-ingestion`. It is a Python service that discovers recovery meeting sources, scrapes local source websites, normalizes raw records into canonical meetings, stores review flags, and exports `snapshots/latest.json`.

The command entry point is `app/cli.py`. Source discovery modules live under `app/sources/`; AA world-service discovery is `app/sources/aa_world_services.py`. Browser scraping lives under `app/scraping/`. The database repository code is `app/storage/repositories.py`. Snapshot export is `app/export/snapshot.py`.

A source is a row in the `sources` database table. A canonical meeting is a normalized row in `canonical_meetings` that can be exported to SoberSpace. A review flag is a warning or error row in `review_flags`; warnings can be acceptable after audit, but errors must be resolved or deliberately excluded before publication. A controlled batch means a limited scrape command using `--limit`, so failures are small enough to inspect.

The local database URL is the default from `app/config.py`: `postgresql:///recovery_meeting_ingestion_dev`. The virtual environment is `.venv/`.

## Plan of Work

First, run AA discovery in dry-run mode and then persisted mode:

    .venv/bin/python -m app.cli discover-sources --fellowship aa --dry-run
    .venv/bin/python -m app.cli discover-sources --fellowship aa --no-dry-run

Then query the source registry to see whether discovery added new rows and whether obvious noise appeared. If obvious non-source rows are discovered, add filtering in `app/sources/aa_world_services.py` with tests in `tests/test_discovery.py`.

Next, run a controlled AA scrape batch into a timestamped artifact directory:

    .venv/bin/python -m app.cli scrape-all --fellowship aa --limit 20 --max-pages-per-source 12 --output-dir scrape_artifacts/aa-controlled-YYYYMMDDTHHMMSSZ --no-dry-run

Inspect terminal output and artifact summaries. A successful source has `scrape_status=succeeded` and nonzero `records_extracted`. A zero-result source has `scrape_status=succeeded` but `records_extracted=0`. A failed source has `scrape_status=failed` and an error message. Use `debug-scrape-source` on representative zero-result or failed sources.

If a repeated page pattern fails, update scraper extraction in the smallest relevant module, usually `app/scraping/extract_meetings.py`, `app/scraping/bmlt_hints.py`, or source classification/discovery code. Add tests for the pattern, then run:

    .venv/bin/ruff check app tests
    .venv/bin/pytest
    .venv/bin/mypy app

After the controlled batch is good enough, run the full AA scrape:

    .venv/bin/python -m app.cli scrape-all --fellowship aa --max-pages-per-source 12 --no-dry-run

Finally, audit review flags and export a new snapshot:

    .venv/bin/python -m app.cli export-snapshot --no-dry-run

The full AA pass has completed. Future AA work should start from warning audit and targeted reruns rather than another full scrape.

## Concrete Steps

All commands are run from `/home/michaelroddy/repos/recovery-meeting-ingestion`.

Baseline commands already run:

    git status --short --branch
    jq -r '.meetings | group_by(.fellowship)[] | {fellowship: .[0].fellowship, count: length} | @json' snapshots/latest.json
    psql postgresql:///recovery_meeting_ingestion_dev -c "SELECT fellowship, COUNT(*) FROM sources GROUP BY fellowship ORDER BY fellowship;"
    psql postgresql:///recovery_meeting_ingestion_dev -c "SELECT fellowship, COUNT(*) FROM canonical_meetings GROUP BY fellowship ORDER BY fellowship;"

Observed baseline:

    snapshot latest.json: aa=114, ca=2341, na=2681
    sources table: aa=1107, ca=123, na=929
    canonical_meetings table: aa=114, ca=3144, na=2681
    AA review flags: 0 errors, 20 warnings

AA discovery dry-run transcript excerpt:

    Source discovery dry_run=True
    fellowship: aa
    candidates: 1107
    - aa-d1c5739e75b5 General Service Office of U.S. and Canada phoneline tel:2128703400
    - aa-57245598aa83 12th District Central Office http://www.augustaaa.org
    ... 1097 more
    output: not written because --dry-run was set

Persisted AA discovery and adapter preservation notes:

    Source discovery dry_run=False
    fellowship: aa
    candidates: 1107
    stored_sources: 1107

    UPDATE sources SET adapter_type = 'playwright_browser', requires_browser = true ...
    UPDATE 8

    RUN_DB_TESTS=1 .venv/bin/pytest tests/test_repositories_db.py -q
    7 passed in 1.38s

Final AA resume and export transcript excerpts:

    PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers .venv/bin/python -m app.cli scrape-all --fellowship aa --offset 514 --max-pages-per-source 3 --concurrency 8 --output-dir scrape_artifacts/aa-full-resume-20260524T093353Z --no-dry-run
    Scrape all dry_run=False
    sources: 164
    ...
    progress: 164/164

    awk summary for scrape_artifacts/aa-full-resume-20260524T093353Z.log:
    succeeded=147
    failed=17
    candidates=13884
    review_flags=9317

    .venv/bin/python -m app.cli import-artifacts scrape_artifacts/aa-full-resume-20260524T092816Z/aa-4f1f1cdaa6f9/summary.json --no-dry-run
    records_extracted: 576
    candidates_normalized: 576
    canonical_meetings_upserted: 576

    .venv/bin/python -m app.cli export-snapshot --no-dry-run
    active_meetings: 99416
    stale_meetings: 0
    blocked_by_review: 0
    output: snapshots/meetings-2026-05-24T094908Z.json
    snapshot_id: c6693781-3cb6-4e4c-9146-739b2b42356f

Final exported fellowship counts:

    snapshots/latest.json: aa=94394, ca=2341, na=2681

Montreal timezone cleanup transcript excerpts:

    .venv/bin/python -m app.cli import-artifacts scrape_artifacts/aa-full-resume-20260524T093353Z/aa-fd84ea48efda/summary.json --no-dry-run
    records_extracted: 2098
    candidates_normalized: 2098
    review_flags: 763
    canonical_meetings_upserted: 2098

    SELECT timezone, COUNT(*) ... WHERE source_id='aa-fd84ea48efda':
    America/Toronto=1765
    America/Moncton=11
    America/Iqaluit=1

    .venv/bin/python -m app.cli export-snapshot --no-dry-run
    active_meetings: 99416
    blocked_by_review: 0
    output: snapshots/meetings-2026-05-24T095621Z.json

## Validation and Acceptance

The AA pass is successful when all of the following are true:

1. AA discovery has been run and any source-registry changes are documented.
2. A controlled AA scrape batch has been run and summarized by successful, zero-result, and failed sources.
3. The final full AA scrape/import has run, or a clear blocker is documented with source IDs and artifacts.
4. `snapshots/latest.json` has been exported after the AA pass.
5. The AA count in `snapshots/latest.json` is higher than the baseline of 114, unless the plan documents why the scrape was blocked before publication.
6. Review flags for AA are audited, with errors resolved or explicitly blocked.

## Idempotence and Recovery

Discovery is idempotent because source rows are upserted by normalized URL and fellowship. Scraping a source is also idempotent at the canonical level because meetings are upserted by source identity fields. Browser scrape outcomes are written to `sources.config.scrape`; a failed scrape is skipped by future `scrape-all` runs unless retried with `--include-failed`. Successful page URLs are also stored in `sources.config.scrape.successful_pages` and tried first on future browser scrapes. Artifact directories are timestamped, so reruns do not overwrite previous evidence.

If a future full run needs to be resumed after it stops, derive the offset from the completed artifact directory count and use a smaller per-source page cap:

    PROCESSED=$(find scrape_artifacts/aa-full-20260523T2341Z -mindepth 1 -maxdepth 1 -type d | wc -l)
    PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers .venv/bin/python -m app.cli scrape-all --fellowship aa --offset "$PROCESSED" --max-pages-per-source 3 --output-dir scrape_artifacts/aa-full-resume-YYYYMMDDTHHMMSSZ --no-dry-run

Historical resume command after the 2026-05-24T10:25+01:00 pause:

    OUT="scrape_artifacts/aa-full-resume-$(date -u +%Y%m%dT%H%M%SZ)"
    PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers .venv/bin/python -m app.cli scrape-all --fellowship aa --offset 463 --max-pages-per-source 3 --concurrency 4 --output-dir "$OUT" --no-dry-run > "$OUT.log" 2>&1

`--concurrency 10` and `--concurrency 6` were both functional, but drove CPU to uncomfortable levels in VS Code. `--concurrency 4` was chosen as the current safer resume setting. Running from a normal shell with output redirected to a log should avoid VS Code terminal rendering overhead; `.vscode/settings.json` now excludes `scrape_artifacts/**` and `.playwright-browsers/**` from VS Code file watching/search.

After VS Code was closed, `--concurrency 8` was used successfully for the final 164-source resume. Be careful using numeric offsets after a partial run has marked sources failed, because `scrape-all` excludes failed sources unless `--include-failed` is passed before applying `--offset`. For future resumes, compare artifact source IDs against the selected source list or resume from an unchanged shell session when possible.

If a scrape batch produces bad canonical records, inspect `review_flags`, source artifacts, and raw payloads before exporting. Prefer fixing extraction and rerunning the affected source over deleting database rows manually.

## Artifacts and Notes

Important AA artifacts:

- `scrape_artifacts/aa-full-resume-20260524T092816Z`: concurrency-4 resume from offset 463. It reached progress 51/215 before the run was stopped/replaced. Its Northern Virginia artifact `aa-4f1f1cdaa6f9/summary.json` is the successful 576-record artifact used to restore that source after a later failed scrape.
- `scrape_artifacts/aa-full-resume-20260524T093353Z`: concurrency-8 final resume from offset 514. It completed 164/164, with 147 succeeded, 17 failed, 13,884 normalized candidates, and 9,317 review flags.
- `snapshots/meetings-2026-05-24T094908Z.json`: first final AA export after clearing open error flags.
- `snapshots/meetings-2026-05-24T095621Z.json` and `snapshots/latest.json`: refreshed export after clearing the Montreal missing-timezone cluster, with `aa=94394`, `ca=2341`, and `na=2681`.

## Interfaces and Dependencies

Use the existing CLI in `app/cli.py`. Use the existing Playwright browser scraper through `scrape-all` and `debug-scrape-source`. Use the existing database connection from `app/config.py`. Do not add a second scraping framework unless the controlled batch proves the existing browser-first path cannot handle a repeated AA pattern.

Plan revision note: Created on 2026-05-23 to turn the user's request to scrape AA meetings into a repeatable, auditable operational pass.

Plan revision note: Updated on 2026-05-24 after completing the AA full scrape/import, fixing failed-scrape persistence, clearing open review errors, and exporting `snapshots/meetings-2026-05-24T094908Z.json`.

Plan revision note: Updated on 2026-05-24 after clearing the largest AA missing-timezone cluster and exporting `snapshots/meetings-2026-05-24T095621Z.json`.

# Add Snapshot Semantic Dedupe and Duplicate Quality Gates

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan follows `PLANS.md` in the repository root.

## Purpose / Big Picture

SoberSpace should show one recovery meeting card for one real-world meeting, even when ingestion sees that meeting from several regional, area, or national source pages. Today the ingestion snapshot preserves one exported meeting per canonical source row. That makes the downstream app faithfully render duplicate rows, including NA Ireland meetings imported under several Ireland source IDs, CA Ireland weekday rows that should be one card with many occurrences, and AA regional/national feed overlap. After this work, snapshot export will consolidate semantic duplicates, merge weekly occurrences, report duplicate metrics, and fail publication when the duplicate rate is too high to trust.

The observable outcome is a new snapshot whose fellowship counts are materially lower because duplicate meeting rows have been merged, while occurrence counts remain accurate. Running `recovery-meeting-ingestion export-snapshot --dry-run` should print duplicate/consolidation metrics and refuse to write if thresholds are exceeded. Running focused tests should prove that Dingle NA, Portlaoise NA, CA Oz House Galway, and AA Australia overlap collapse as expected.

## Progress

- [x] (2026-05-31T20:50+01:00) Investigated the duplicate issue against the local ingestion database and latest snapshot.
- [x] (2026-05-31T20:50+01:00) Confirmed current snapshot export serializes one canonical row to one snapshot meeting with no semantic consolidation.
- [x] (2026-05-31T20:50+01:00) Confirmed `app.normalize.dedupe.find_duplicate_candidates` only reports fuzzy pairs and is not wired into export.
- [x] (2026-05-31T20:50+01:00) Confirmed downstream SoberSpace import uniqueness is `fellowship + source_id + source_record_id`, which cannot catch cross-source duplicates.
- [x] (2026-05-31T20:37+01:00) Implemented repeatable duplicate metrics and deterministic semantic consolidation in `app/normalize/dedupe.py`.
- [x] (2026-05-31T20:37+01:00) Wired consolidation into `build_snapshot` through a `SnapshotBuildResult` so callers can inspect metrics.
- [x] (2026-05-31T20:39+01:00) Added duplicate quality gates to `export-snapshot` and removed the broad candidate-loading exception handler that wrote empty snapshots.
- [x] (2026-05-31T20:41+01:00) Added targeted regression tests for NA Dingle, NA Portlaoise, CA Oz House Galway, AA Australia overlap, and CLI export safety.
- [x] (2026-05-31T20:51+01:00) Exported, audited, and dry-run imported the replacement snapshot with `--allow-large-drop`; no committed downstream import was run.

## Surprises & Discoveries

- Observation: The latest local `snapshots/latest.json` contains 181,619 meetings: `aa=114,019`, `ca=2,762`, and `na=64,838`.
    Evidence: Running `.venv/bin/python` over `snapshots/latest.json` printed `schema 2026-04-30 generated_at 2026-05-26T21:51:33.714529Z`, `total 181619`, and fellowship counts `{'aa': 114019, 'ca': 2762, 'na': 64838}`.
- Observation: Exact same-occurrence duplicates are large, but broader semantic duplicates are larger.
    Evidence: SQL against exportable DB rows found exact same-occurrence duplicate groups `aa=7,459`, `ca=192`, `na=11,559`. A broader key using fellowship, normalized name, meeting type, venue/address/city/country, and ignoring weekday/time found approximate removable rows `aa=52,742`, `ca=619`, and `na=38,126`.
- Observation: NA Ireland area sources repeatedly imported the same shared meetings.
    Evidence: Dingle NA rows appeared under `na-2d0fad4641a8`, `na-565ff8e141b7`, `na-59ab9cdea751`, `na-d25e759e1533`, and `na-e9c7fc6d1f46`. Portlaoise NA rows appeared under four Ireland sources. Four NA Ireland sources each had 348 active rows and shared `https://www.na-ireland.org/online-meetings/` as a successful page.
- Observation: CA Galway/Oz House is partly a row-shaping issue, not just source overlap.
    Evidence: `ca-23bc07bc85b3` has separate `C.A. Oz House` rows for Monday through Friday at 15:00. Some rows place `Not wheelchair accessible` in the `city` field, which makes exact duplicate detection weaker and points to a parser cleanup need.
- Observation: The CLI can write empty snapshots on DB errors.
    Evidence: `app/cli.py` catches all exceptions while loading snapshot candidates, substitutes `candidates = []`, and continues. Two 128-byte historical snapshot files exist with `"meetings": []`.
- Observation: Consolidation is intentionally large on the current data.
    Evidence: `export-snapshot --no-dry-run` consolidated 181,619 source rows into 91,416 exported meetings, removing 90,203 duplicate source rows. A second consolidation pass over the exported candidates reported zero residual semantic duplicate groups.
- Observation: The downstream importer has its own large-drop safety gate.
    Evidence: A dry-run import without override failed with `recovery meeting snapshot is more than 20 percent smaller than current active data`. Running the same dry run with `--allow-large-drop` completed successfully and reported `Meetings seen: 91416`, `Occurrences written: 144752`, and `Marked stale: 113730`.
- Observation: Spot checks found one overly strict key rule before the committed import.
    Evidence: Preferring geocoded keys over text keys left Dingle and Portlaoise split because one Dingle row had no coordinates and the Portlaoise coordinates differed by 0.0001 degrees. The final implementation prefers normalized address text and only falls back to rounded coordinates when no textual place key exists.
- Observation: Full-project ruff and mypy still expose unrelated pre-existing debt.
    Evidence: Changed files pass ruff, and `app/normalize/dedupe.py` passes mypy. Full-project ruff reports older long lines in `app/review/flags.py` and `app/scraping/ca_source_specific.py`; full-project mypy reports existing errors in `app/normalize/location_quality.py` and `app/scraping/ca_source_specific.py`.

## Decision Log

- Decision: Fix duplicate rendering in ingestion/export, not in the frontend.
    Rationale: The frontend is rendering the data it receives. Frontend dedupe would hide polluted source data while leaving search, filters, detail pages, counts, and import state inconsistent.
    Date/Author: 2026-05-31, Codex.
- Decision: Preserve canonical storage identity and consolidate only at snapshot export for the first implementation.
    Rationale: Storage identity by `source_id + source_record_id` is useful for idempotent scrape reruns and source attribution. Export-time consolidation reduces downstream pollution without destructive database rewrites.
    Date/Author: 2026-05-31, Codex.
- Decision: Start with deterministic semantic keys and conservative merge rules, then use fuzzy matching only for reporting or explicitly reviewed cases.
    Rationale: The export path must be predictable and safe. Fuzzy matching can merge distinct meetings at the same venue if used too broadly.
    Date/Author: 2026-05-31, Codex.
- Decision: Treat exporter DB failures as fatal.
    Rationale: Writing an empty snapshot is more dangerous than failing an export command. A failed export leaves the last good `snapshots/latest.json` untouched.
    Date/Author: 2026-05-31, Codex.
- Decision: Run the downstream importer dry run with `--allow-large-drop`, but do not run a committed import.
    Rationale: The duplicate cleanup intentionally cuts the meeting count by more than 20 percent, which trips the app importer’s safety gate. The override is appropriate for validation only after recording the count drop and duplicate metrics.
    Date/Author: 2026-05-31, Codex.

## Outcomes & Retrospective

Implemented export-time semantic consolidation and duplicate quality gates. The final consolidated snapshot was imported into the SoberSpace app database with the explicit `--allow-large-drop` override after a matching dry run.

The new snapshot is:

    path: snapshots/meetings-2026-05-31T195643Z.json
    snapshot_id: 9a610f24-7868-47f2-8c5f-7f99c17212de
    source_meetings: 181619
    active_meetings: 91416
    duplicate_rows_removed: 90203
    residual_duplicate_rows_removed_on_second_pass: 0

The written snapshot audit reports zero duplicate groups:

    duplicate_metrics:
    - original_count: 91416
    - consolidated_count: 91416
    - removed_count: 0
    - exact_occurrence_duplicate_groups_by_fellowship: none
    - semantic_duplicate_groups_by_fellowship: none
    - removed_by_fellowship: none

The existing location audit now reports 5 `timezone_country_mismatch` findings. Those are not caused by duplicate consolidation and should be handled separately.

The SoberSpace importer dry run with `--allow-large-drop` completed:

    Import run: 0e563404-b143-4a0f-9bab-93e6f8036bab
    Snapshot SHA-256: a847f8067d0729d9ca24cb9a86659c4096b6009b212cbec58623fc8d60fbfee2
    Meetings seen: 91416
    Meetings upserted: 91416
    Occurrences written: 144752
    Marked stale: 113730
    Marked inactive: 0

The committed SoberSpace import completed:

    Import run: 71b0095a-bae5-46c3-9835-4609b8a418db
    Snapshot SHA-256: a847f8067d0729d9ca24cb9a86659c4096b6009b212cbec58623fc8d60fbfee2
    Meetings seen: 91416
    Meetings upserted: 91416
    Occurrences written: 144752
    Marked stale: 113730
    Marked inactive: 0

App database verification after the committed import:

    active meetings by fellowship:
    aa: 61113
    ca: 2119
    na: 28184
    active occurrences: 144752

Representative active app rows now have merged occurrences:

    C.A. Oz House: Monday through Friday at 15:00
    DIngle Online and Physically Open: Tuesday at 19:30 and Friday at 20:30
    Step To Freedom Group Portlaoise: Monday at 20:00 and Saturday at 19:00

Validation:

    .venv/bin/pytest -q
    result: 270 passed, 14 skipped

    git diff --check
    result: passed

    .venv/bin/ruff check app/cli.py app/export/snapshot.py app/normalize/dedupe.py tests/test_cli.py tests/test_dedupe.py tests/test_review_snapshot.py
    result: passed

    .venv/bin/mypy app/normalize/dedupe.py
    result: passed

The SoberSpace import is committed in the app database.

## Context and Orientation

This repository is `/home/michaelroddy/repos/recovery-meeting-ingestion`. It discovers recovery meeting sources, scrapes raw pages, normalizes raw records into canonical meeting rows, stores review flags, and writes JSON snapshots for SoberSpace. The downstream app repository is `/home/michaelroddy/repos/project_radeon`, whose importer upserts meetings by `fellowship + source_id + source_record_id`.

A canonical meeting candidate is a normalized Python object defined in `app/normalize/canonical.py`. It includes fields such as `fellowship`, `source_id`, `source_record_id`, `name`, location fields, and an `occurrences` list. An occurrence is one weekly meeting time with `day_of_week`, `start_time_local`, optional `end_time_local`, and `timezone`.

Snapshot export starts in `app/cli.py` in the `export_snapshot` command. It loads active candidates from `CanonicalMeetingRepository.list_active_candidates_for_snapshot` in `app/storage/repositories.py`, then calls `app/export/snapshot.py:build_snapshot`. The current `build_snapshot` normalizes locations and serializes each candidate directly into one `SnapshotMeeting`.

The existing `app/normalize/dedupe.py` file contains `find_duplicate_candidates`, but that helper only compares pairs and returns likely duplicate pairs. It does not group candidates, merge occurrences, choose a primary source record, or integrate with snapshot export.

Raw browser scraping creates source record IDs in `app/scraping/raw_records.py`. When a scraped payload lacks an explicit source ID, it hashes fields including `name`, `day`, `time`, `address_line1`, `city`, `online_url`, and `row_index`. This makes one real-world meeting appear as several canonical rows when a source emits one row per weekday.

## Plan of Work

First, add duplicate audit types and functions in `app/normalize/dedupe.py`. Define a semantic meeting key from normalized fellowship, meeting type, name, physical place, and online/phone access. Physical place should use conservative normalized text from `venue_name`, `address_line1`, `address_line2`, `city`, `region`, `postal_code`, `country`, `country_code`, and optionally rounded latitude/longitude when present. The key must not include day or time because those belong in merged occurrences. The audit should report exact occurrence duplicate groups, semantic duplicate groups, rows in duplicate groups, estimated removable rows, and examples.

Second, implement `consolidate_duplicate_candidates(candidates: list[CanonicalMeetingCandidate]) -> ConsolidationResult` in `app/normalize/dedupe.py`. `ConsolidationResult` should expose `candidates`, `metrics`, and examples. For each semantic group, choose a primary candidate deterministically. Prefer candidates with more complete location fields, non-approximate coordinates, more occurrences, and source IDs not marked as excluded by upstream filtering; use source ID and source record ID as final stable tie-breakers. Merge occurrences by unique `(day_of_week, start_time_local, end_time_local, timezone)`, sorted by weekday and time. Merge formats as a sorted unique list. Preserve the primary candidate's `source_id`, `source_record_id`, `source_url`, and display fields for now.

Third, call consolidation from `build_snapshot` after `normalize_candidate_location` and before constructing `SnapshotMeeting` objects. This keeps existing location cleanup ahead of dedupe, so keys see normalized countries, regions, and address repairs.

Fourth, add a quality gate to `export-snapshot`. The command should print pre- and post-consolidation counts, duplicate groups, rows removed, and duplicate rates by fellowship. Add CLI options for thresholds, with conservative defaults that fail on materially high duplicate rates. A dry run should evaluate the gate without writing a file. A non-dry-run export should refuse to write when the gate fails. Replace the broad candidate-loading `except Exception` with a surfaced error so DB failures abort the command.

Fifth, add targeted unit tests. Tests should create in-memory `CanonicalMeetingCandidate` instances and call `build_snapshot` or the new consolidation function. Include:

- NA Dingle: same source record IDs and meeting details repeated under multiple NA Ireland source IDs should produce one or a small number of meeting cards with merged occurrences.
- NA Portlaoise: Monday and Saturday rows repeated under several NA Ireland source IDs should produce one card with two occurrences.
- CA Oz House Galway: Monday through Friday rows from the same source should produce one card with five occurrences despite minor punctuation differences and known bad city text such as `Not wheelchair accessible`.
- AA Australia: national and NSW source overlap should choose one primary row and not export two cards for the same occurrence.

Sixth, add an operational audit command or extend `audit-snapshot-quality` to include duplicate metrics for a written snapshot. This is useful after export and before downstream import. The command should print fellowship-level counts and examples, not only pass/fail.

Finally, export and verify a replacement snapshot. Run `export-snapshot --dry-run`, then `export-snapshot --no-dry-run` only when the gate passes or thresholds have been intentionally adjusted with a documented reason. Run the SoberSpace importer from `/home/michaelroddy/repos/project_radeon` in dry-run mode against the new snapshot. Do not run a committed SoberSpace import until duplicate counts and total counts are accepted.

## Concrete Steps

Run all commands from `/home/michaelroddy/repos/recovery-meeting-ingestion` unless otherwise noted.

Inspect the relevant code before editing:

    nl -ba app/export/snapshot.py | sed -n '1,90p'
    nl -ba app/normalize/dedupe.py | sed -n '1,140p'
    nl -ba app/cli.py | sed -n '731,766p'
    nl -ba app/scraping/raw_records.py | sed -n '1,60p'

Add tests first where practical:

    .venv/bin/pytest tests/test_dedupe.py tests/test_review_snapshot.py

After implementing consolidation, run focused tests:

    .venv/bin/pytest tests/test_dedupe.py tests/test_review_snapshot.py tests/test_location_quality.py

Run a dry-run export and inspect its printed metrics:

    .venv/bin/python -m app.cli export-snapshot --dry-run

After the dry run passes the quality gate, write a snapshot:

    .venv/bin/python -m app.cli export-snapshot --no-dry-run

Audit the written snapshot:

    .venv/bin/python -m app.cli audit-snapshot-quality snapshots/latest.json

Dry-run the downstream importer from the app repository:

    cd /home/michaelroddy/repos/project_radeon
    GOCACHE=/tmp/go-build GOMODCACHE=/tmp/go-mod go run ./cmd/import-recovery-meetings --snapshot /home/michaelroddy/repos/recovery-meeting-ingestion/snapshots/latest.json --dry-run

Run full validation before considering the work complete:

    cd /home/michaelroddy/repos/recovery-meeting-ingestion
    .venv/bin/pytest
    git diff --check

## Validation and Acceptance

The new tests must fail before consolidation and pass after it. `tests/test_dedupe.py` should prove grouping and occurrence merging. `tests/test_review_snapshot.py` should prove `build_snapshot` exports consolidated meetings and does not leak raw payloads.

`export-snapshot --dry-run` must print duplicate/consolidation metrics and must not write a snapshot. If duplicate rates exceed configured thresholds, the command must exit non-zero and explain which threshold failed.

`export-snapshot --no-dry-run` must not write an empty snapshot if database access fails. To validate this behavior, patch or monkeypatch `connect` in a CLI test to raise an exception and assert the command exits non-zero and no output file is written.

For the current local data, acceptance requires material count reduction from the current `181,619`-meeting latest snapshot, with preserved weekly occurrence coverage for merged examples. The exact target count should be documented in `Outcomes & Retrospective` after implementation because the final number depends on conservative key design.

The SoberSpace dry-run importer must complete successfully against the new snapshot. The dry-run output should show a lower `meetings_seen` count than the polluted snapshot and an occurrence count that remains plausible after merge.

## Idempotence and Recovery

The implementation should be additive and safe to rerun. Export-time consolidation does not mutate canonical database rows. If a merge rule is too broad, revert or narrow the key logic and regenerate the snapshot; no database cleanup is needed.

Snapshot writing should remain atomic at the file level already used by `write_snapshot`. The command should only update `snapshots/latest.json` after successfully building and passing the quality gate.

Do not delete existing historical snapshots during this work. Historical empty snapshots can remain as evidence unless the user explicitly asks to clean them up.

Do not run a committed SoberSpace import until a dry-run import has completed and the duplicate metrics are acceptable. The dry-run import is safe and can be repeated.

## Artifacts and Notes

Investigation evidence from 2026-05-31:

    latest snapshot: snapshots/latest.json
    schema: 2026-04-30
    generated_at: 2026-05-26T21:51:33.714529Z
    total meetings: 181619
    fellowship counts: aa=114019, ca=2762, na=64838

Exportable DB active counts after source exclusions and open error review filtering:

    aa=114073
    ca=2762
    na=64840

Exact same-occurrence duplicates in exportable DB rows:

    aa: 7459 duplicate groups, 15810 rows in groups, 8351 removable occurrence rows
    ca: 192 duplicate groups, 384 rows in groups, 192 removable occurrence rows
    na: 11559 duplicate groups, 33377 rows in groups, 21818 removable occurrence rows

Broader semantic duplicate footprint using fellowship, normalized name, meeting type, venue/address/city/country, and ignoring weekday/time:

    aa: 16650 identity groups, 69392 rows in groups, 52742 removable rows
    ca: 358 identity groups, 977 rows in groups, 619 removable rows
    na: 12447 identity groups, 50573 rows in groups, 38126 removable rows

Representative overlap pairs:

    aa-08512eb5f89d AA NSW Service Council Inc
    aa-b60e7af83fb9 General Service Office Of Alcoholics Anonymous Australia
    overlap_count: 2224

    aa-150a4d339c23 Region Nord-est Du Quebec
    aa-fd84ea48efda Oficina Intergrupal De Alcoholicos Anonimos De Habla Hispana De Montreal
    overlap_count: 1655

    aa-3090c74ccb53 St. Cloud Intergroup
    aa-8d7bc6feeb7a Greater Minneapolis Intergroup
    overlap_count: 851

Known problematic snapshots:

    snapshots/meetings-2026-05-26T121358Z.json
    snapshots/meetings-2026-05-26T213046Z.json

Both are 128-byte JSON files with an empty `meetings` array, produced because `export-snapshot` swallowed candidate-loading errors.

## Interfaces and Dependencies

In `app/normalize/dedupe.py`, add data structures similar to:

    @dataclass(frozen=True)
    class DuplicateMetrics:
        original_count: int
        consolidated_count: int
        removed_count: int
        exact_occurrence_duplicate_groups_by_fellowship: dict[str, int]
        semantic_duplicate_groups_by_fellowship: dict[str, int]
        removed_by_fellowship: dict[str, int]

    @dataclass(frozen=True)
    class ConsolidationResult:
        candidates: list[CanonicalMeetingCandidate]
        metrics: DuplicateMetrics
        examples: list[DuplicateExample]

    def consolidate_duplicate_candidates(
        candidates: list[CanonicalMeetingCandidate],
    ) -> ConsolidationResult:
        ...

Keep `find_duplicate_candidates` for compatibility unless all callers are migrated. The new consolidation path should use only standard library modules plus existing project types. `rapidfuzz` may remain for pair reporting, but the export merge should not require fuzzy scores for its default behavior.

In `app/export/snapshot.py`, either make `build_snapshot` return only a `Snapshot` and expose metrics through a helper, or add a second function such as:

    def build_snapshot_with_quality(candidates: list[CanonicalMeetingCandidate]) -> SnapshotBuildResult:
        ...

Prefer a result object if CLI quality gates need metrics without recomputing.

In `app/cli.py`, `export_snapshot` should call the result-producing builder, print metrics, evaluate thresholds, and fail before writing when the gate fails. It should no longer catch all exceptions from DB candidate loading.

Plan revision note: Created on 2026-05-31 after investigation confirmed duplicate pollution is caused by ingestion/export row shaping rather than frontend rendering.

Plan revision note: Updated on 2026-05-31 after implementing export-time semantic consolidation, quality gates, regression tests, snapshot export, snapshot audit, and downstream importer dry-run validation.

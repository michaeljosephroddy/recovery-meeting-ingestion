# Normalize Meeting Locations Before Export

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan follows `PLANS.md` in the repository root.

## Purpose / Big Picture

SoberSpace frontend filters depend on clean meeting location fields. After this change, imported meeting records should preserve valid ambiguous places such as London, Ontario or Greater London, Ontario while preventing navigation text and schedule links from appearing as meetings. The visible result is that records with address text like `Ontario, CA 91764, USA` export as city `Ontario`, region `California`, country `United States`, and scraper artifacts such as `PRINTABLE MEETING SCHEDULE` are blocked from snapshots by review errors.

## Progress

- [x] (2026-05-26T10:03:10Z) Investigated the latest snapshot and confirmed the `Greater London, Ontario, Canada` example came from a heuristic scrape artifact named `PRINTABLE MEETING SCHEDULE`.
- [x] (2026-05-26T10:03:10Z) Identified that `app/adapters/static_html.py` preserves payload/source `region` before inferred address region, causing values such as city `Ontario` to leak into the `region` field for US addresses.
- [x] (2026-05-26T10:14:00Z) Added source-aware normalization in `app/normalize/location_quality.py` and call it from `app/ingest.py`.
- [x] (2026-05-26T10:14:00Z) Added `location_text_artifact` error review flags for obvious schedule/navigation/contact artifacts.
- [x] (2026-05-26T10:14:00Z) Added tests for valid Canadian London/Greater London, US Ontario California, source override, and artifact blocking.
- [x] (2026-05-26T10:15:00Z) Ran focused tests: `18 passed`.
- [x] (2026-05-26T10:21:00Z) Ran full test suite: `239 passed, 13 skipped`.
- [x] (2026-05-26T10:27:00Z) Re-imported targeted local artifacts for `na-24725a7be4e0`, `aa-ed94de7744aa`, and `na-12fba450ac58`.
- [x] (2026-05-26T10:32:00Z) Exported `snapshots/meetings-2026-05-26T101102Z.json` and verified the targeted records are corrected or blocked.
- [x] (2026-05-26T10:36:00Z) Deferred SoberSpace import for the new 212,151-meeting snapshot until the broader local DB audit is resolved.

## Surprises & Discoveries

- Observation: The bad frontend row was not invalid because `Greater London, Ontario, Canada` is impossible; the user clarified Greater London can be a valid Ontario locality. The concrete row is bad because it is a scraped schedule/navigation artifact.
    Evidence: `scrape_artifacts/na-full-20260524T163000Z/na-24725a7be4e0/summary.json` shows the payload has name `PRINTABLE MEETING SCHEDULE`, venue text about virtual meeting listings, and method `heuristic_sequence_text`.
- Observation: Many `region` values are not administrative regions. They include service areas, counties, cities, and online labels.
    Evidence: A snapshot profile showed many US `region` values like `Oklahoma City`, `Area 32`, `Online`, and `Philadelphia County`.
- Observation: Preserving UK locality-style region text is currently required by existing tests.
    Evidence: The focused test run initially failed because `Chelsea London, UK` normalized to `None`; the rule was adjusted to preserve non-admin UK region text while still cleaning US, Canada, and Australia admin-region filters.
- Observation: The local ingestion database currently exports 212,151 meetings, substantially more than the last imported SoberSpace snapshot count of 173,483.
    Evidence: `export-snapshot --no-dry-run` wrote `snapshots/meetings-2026-05-26T101102Z.json` with `active_meetings: 212151` and `blocked_by_review: 96`.
- Observation: The new full snapshot still has broad quality issues unrelated to the targeted location fix.
    Evidence: `audit-snapshot-quality snapshots/meetings-2026-05-26T101102Z.json --examples 2 --top-sources 20` reported `20833 timezone_country_mismatch` and `30 high_confidence_country_conflict`.

## Decision Log

- Decision: Treat place names like `London` and `Greater London` as ambiguous locality text, not country inference by themselves.
    Rationale: London and Greater London can be valid in Ontario, Canada as well as the UK. Country and region evidence should decide how filters classify the record.
    Date/Author: 2026-05-26, Codex.
- Decision: Add artifact review flags instead of silently dropping rows in the normalizer.
    Rationale: Existing snapshot export excludes open error review flags, which gives operators visibility into why records are blocked while preventing bad rows from reaching SoberSpace.
    Date/Author: 2026-05-26, Codex.
- Decision: Keep source metadata as a fallback only for location normalization.
    Rationale: A broad source can contain remote online meetings or embedded feeds. Record-level address/postcode/country evidence must override source country and region.
    Date/Author: 2026-05-26, Codex.

## Outcomes & Retrospective

The code-level work is complete: tests demonstrate valid Canadian London records remain Canadian, US Ontario records export with California as region, and schedule/navigation artifacts receive blocking review errors.

Full-suite validation passes and the targeted local DB rows are corrected. The new full snapshot was intentionally not imported into SoberSpace because the local DB has broader quality and count drift that should be resolved before downstream import.

## Context and Orientation

The ingestion pipeline converts raw records into `CanonicalMeetingCandidate` objects in `app/ingest.py`. Each source adapter, such as `app/adapters/static_html.py`, creates candidates from raw payloads. Candidates are persisted into `canonical_meetings` by `app/storage/repositories.py`. Snapshot export in `app/export/snapshot.py` calls `normalize_candidate_location` from `app/normalize/location_quality.py` before writing JSON.

A review flag is a row-level quality marker represented by `ReviewFlag` in `app/review/flags.py`. Snapshot export excludes active meetings that have open review flags with severity `error`, so error flags are the existing mechanism for blocking suspect records from downstream import without deleting them.

## Plan of Work

First, extend `app/normalize/location_quality.py` so `normalize_candidate_location` accepts optional source context. The normalizer will canonicalize countries, infer country and administrative region from address tokens such as `CA 91764` or `ON`, and use source country/region only as fallback. For United States, Canada, and Australia, it will keep `region` only when it is a recognized state/province/territory name or abbreviation. It will not infer UK from `London` or `Greater London` alone.

Second, call this normalizer from `app/ingest.py` immediately after each adapter creates a candidate. Snapshot export will continue to call it as a safety pass.

Third, add review flags in `app/review/flags.py` for obvious scraper artifacts in frontend-facing text fields. The first targeted cases are schedule/navigation rows such as `PRINTABLE MEETING SCHEDULE`, email addresses in city, weekdays in city/name fields, and phrases such as `are listed here:` or `Secondary Menu`.

Fourth, add tests in `tests/test_location_quality.py` and `tests/test_review_snapshot.py` that prove valid ambiguous Canadian locations are preserved, US Ontario is normalized to California region, and schedule/navigation artifacts are flagged with severity `error`.

## Concrete Steps

Run all commands from `/home/michaelroddy/repos/recovery-meeting-ingestion`.

After editing, run:

    .venv/bin/pytest tests/test_location_quality.py tests/test_review_snapshot.py

Then run:

    .venv/bin/pytest

The full test run completed successfully.

## Validation and Acceptance

Acceptance is met when:

- `London, ON, Canada` normalizes to city `London`, region `Ontario`, country `Canada`.
- `Greater London`, region `Ontario`, country `Canada` remains Canadian and is not forced to the UK.
- `810 E Princeton St, Ontario, CA 91764, USA` normalizes to city `Ontario`, region `California`, country `United States`.
- A candidate named `PRINTABLE MEETING SCHEDULE` receives a `location_text_artifact` error flag and is blocked from snapshots by the existing export query.
- The focused pytest command passes.
- The full pytest command passes.

The targeted data cleanup acceptance was verified in the local ingestion DB and new snapshot:

- `PRINTABLE MEETING SCHEDULE` remains traceable in `canonical_meetings`, but has an open `location_text_artifact` error flag and is excluded from snapshots.
- `810 E Princeton St, Ontario, CA 91764` exports as city `Ontario`, region `California`, country `United States`.
- `Sarnia, Ontario` from the Mississippi NA source now exports as city `Sarnia`, region `Ontario`, country `Canada`.

## Idempotence and Recovery

The code changes are additive and can be run repeatedly. Re-ingesting a source will upsert normalized candidates and replace review flags for that source through existing repository behavior. If a normalizer rule is too aggressive, revert that rule and rerun the focused tests before reprocessing production snapshots.

## Artifacts and Notes

Important investigation evidence:

    source_id: na-24725a7be4e0
    source_record_id: 4e9023a7cbc6c484
    name: PRINTABLE MEETING SCHEDULE
    city: Greater London
    region: Ontario
    country: Canada
    source_url: https://www.gtascna.org/home/meetings

Focused validation transcript:

    .venv/bin/pytest tests/test_location_quality.py tests/test_review_snapshot.py
    collected 18 items
    tests/test_location_quality.py ...........
    tests/test_review_snapshot.py .......
    18 passed in 0.17s

Full validation transcript:

    .venv/bin/pytest
    collected 252 items
    239 passed, 13 skipped in 8.12s

Targeted re-import evidence:

    na-24725a7be4e0: candidates=2, flags=1, run=919fb2c4-3bc7-422c-8678-2e3210bd2026
    aa-ed94de7744aa: candidates=1013, flags=0, run=a841dbca-0ce2-4644-9730-0600c94ad7ac
    na-12fba450ac58: candidates=1919, flags=0, run=eb74e48a-896c-46aa-af29-9e43d90b47bc

New snapshot evidence:

    output: snapshots/meetings-2026-05-26T101102Z.json
    snapshot_id: 3a2a7c83-7c34-423e-b079-2304a89d8111
    sha256: e97c4d639183535786b29471524f659c4e9841ae42d753a4ec7d62d681de012e

Revision note, 2026-05-26: The implementation now runs location normalization before persistence, keeps valid Canadian London and Greater London records Canadian, normalizes US city/state collisions, and flags schedule/navigation artifacts. The plan was updated to record focused validation and the UK region preservation decision.

Revision note, 2026-05-26: The plan now records full test validation, targeted artifact re-imports, the new snapshot, and the decision not to import that snapshot into SoberSpace while broader local DB audit issues remain.

## Interfaces and Dependencies

`app.normalize.location_quality.normalize_candidate_location(candidate, source=None)` must return a `CanonicalMeetingCandidate`. The optional `source` parameter is an `app.sources.registry.Source` and provides fallback country, region, and config metadata.

`app.review.flags.flags_for_candidate(candidate)` must continue returning `list[ReviewFlag]` and now include error flags for location text artifacts.

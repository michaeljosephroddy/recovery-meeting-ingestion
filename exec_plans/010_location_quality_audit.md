# Recovery Meeting Location Quality Audit and Normalization

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This document follows the repository requirements in `PLANS.md`.

## Purpose / Big Picture

Recovery meeting records currently can reach the mobile app with contradictory location fields, such as an address that says `London, UK` while the `country` field says `United States`. After this change, snapshot export will apply a small, deterministic location normalization pass so obvious country aliases and contradictions are fixed before the backend import sees them. Operators will also be able to run a repeatable snapshot audit command to count remaining high-confidence issues and inspect examples.

The behavior is visible by running tests that create records like `London, UK` with the wrong country and by running the CLI audit against an existing snapshot file. The exported snapshot should contain `United Kingdom` for that record instead of `United States`.

## Progress

- [x] (2026-05-25) Audited the latest snapshot manually and confirmed high-confidence missing-country, country-conflict, and timezone/country mismatch classes.
- [x] (2026-05-25) Created this ExecPlan to keep the data-quality work self-contained.
- [x] (2026-05-25) Added reusable location-quality normalization and audit helpers in `app/normalize/location_quality.py`.
- [x] (2026-05-25) Wired the normalization helper into `app/export/snapshot.py`.
- [x] (2026-05-25) Added `audit-snapshot-quality` in `app/cli.py` for arbitrary snapshot JSON files.
- [x] (2026-05-25) Added focused tests for normalization, audit counts, and false positives in `tests/test_location_quality.py` and `tests/test_review_snapshot.py`.
- [x] (2026-05-25) Ran targeted tests, full tests, targeted lint, and mypy for the new core/export modules; recorded evidence below.

## Surprises & Discoveries

- Observation: A broad first audit over-counted country conflicts because short abbreviations such as `WA` and `NT` can be valid Australian regions while also looking like United States or Canada abbreviations.
  Evidence: Australian records like `Albany WA 6330, Australia` were initially counted as United States conflicts because `WA` is also Washington.
- Observation: The problematic London record already exists in the exported ingestion snapshot and is not created by the mobile app.
  Evidence: `aa-c592e77d0762` records have `address_line1: London, UK`, `region: Chelsea London, UK`, and `country: United States`.
- Observation: Two-letter country aliases are safe to canonicalize when they appear in the `country` field, but are too ambiguous inside address segments.
  Evidence: A CLI audit pass that treated `CA` and `AU` as location segment countries over-counted conflicts because those tokens can mean California/Canada and Australia/state-like abbreviations depending on context. The final code excludes `au`, `ca`, and `us` from location segment inference while still canonicalizing them in declared country fields.
- Observation: Full-repository lint and direct mypy over `app/cli.py` still reveal existing unrelated issues in `app/scraping/ca_source_specific.py`.
  Evidence: `ruff check` reports four pre-existing E501 lines in `app/scraping/ca_source_specific.py`; `mypy app/cli.py` follows imports and reports nine pre-existing type errors in that same file. Targeted lint for touched files and mypy for `app/normalize/location_quality.py app/export/snapshot.py` pass.

## Decision Log

- Decision: Use whole address segments and well-known postcode patterns for automatic country inference, not arbitrary substring matching.
  Rationale: Whole-segment matching avoids false positives like `Ireland St`, `Prince of Wales Dr`, and `Denmark WA`.
  Date/Author: 2026-05-25 / Codex
- Decision: Normalize during snapshot export rather than only in the frontend or backend importer.
  Rationale: The snapshot is the handoff artifact between ingestion and Project Radeon backend import. Fixing it there improves search/filter correctness and app display without hiding bad source data downstream.
  Date/Author: 2026-05-25 / Codex
- Decision: Keep the audit command read-only and report remaining issues rather than failing export.
  Rationale: Some sources need adapter-specific cleanup and review. The export normalization fixes high-confidence one-country cases, while the audit gives operators a prioritized list without blocking all snapshot generation.
  Date/Author: 2026-05-25 / Codex
- Decision: Strip trailing country-only address segments once the country field has been inferred or canonicalized.
  Rationale: Correcting `London, UK` from `United States` to `United Kingdom` would still leave duplicated display text if `UK` stayed in `address_line1`. Removing only a final whole segment such as `UK`, `Australia`, or `Holandia` is idempotent and avoids touching street names.
  Date/Author: 2026-05-25 / Codex

## Outcomes & Retrospective

Implemented a reusable normalization/audit module, export-time normalization, a CLI audit command, and focused tests. The current latest snapshot audit now reports conservative high-confidence counts through the CLI:

    total_meetings: 173483
    high_confidence_missing_country: 843
    high_confidence_country_conflict: 810
    timezone_country_mismatch: 128

Generated snapshots will now canonicalize country aliases, correct one-country explicit contradictions such as `London, UK` plus `United States`, and strip trailing country-only address segments before the backend import receives the data. Remaining large source-level issues still need follow-up in individual adapters or source-specific cleanup.

## Context and Orientation

The ingestion repository exports recovery meeting data through `app/export/snapshot.py`. The function `build_snapshot` receives `CanonicalMeetingCandidate` objects from the database and creates a `Snapshot` containing `SnapshotMeeting` rows. The backend importer in the separate Project Radeon backend stores those fields as provided, and the mobile app displays them by joining address fields. Therefore a bad `country` in the snapshot becomes a bad displayed address and an incorrect search/filter field.

The canonical models live in `app/normalize/canonical.py`. The CLI entry point is `app/cli.py`, which uses Typer commands. Tests are in `tests/` and are run with `pytest`.

In this plan, a "country alias" means a common alternate spelling or code for a country, such as `USA`, `US`, `UK`, `Wielka Brytania`, `Holandia`, or `Niemcy`. A "high-confidence conflict" means the country field says one country while an address segment or postcode clearly says another.

## Plan of Work

Add a new module `app/normalize/location_quality.py`. It will define pure functions for canonical country names, country inference from location fields, candidate normalization, and snapshot auditing. The module must avoid network calls and database access so it can be tested with small in-memory records and run over snapshot JSON files.

Update `app/export/snapshot.py` so each `CanonicalMeetingCandidate` is normalized before it is copied into a `SnapshotMeeting`. This is where `country="USA"` becomes `United States`, missing countries are filled from explicit address country segments, and obvious country conflicts like `London, UK` plus `United States` become `United Kingdom`.

Add a Typer command in `app/cli.py` named `audit-snapshot-quality`. It will accept a snapshot JSON path, run the same audit rules, and print total meetings plus counts for country aliases, missing countries, country conflicts, and timezone/country mismatches. It should show a few examples for each issue class so operators can decide which source adapters need follow-up.

Add tests in `tests/test_location_quality.py` and extend `tests/test_review_snapshot.py` as needed. Tests should cover the specific London case, missing country from `Japan`, country alias canonicalization from `USA`, and false-positive avoidance for `Ireland St, Bright VIC 3741, Australia`.

## Concrete Steps

Work from `/home/michaelroddy/repos/recovery-meeting-ingestion`.

Run targeted tests after adding the module:

    pytest tests/test_location_quality.py tests/test_review_snapshot.py

Actual result:

    13 passed in 0.28s

Run broader validation if the targeted tests pass:

    pytest

Actual result:

    234 passed, 13 skipped in 8.76s

Run the CLI audit manually against the latest snapshot:

    recovery-meeting-ingestion audit-snapshot-quality snapshots/meetings-2026-05-25T143729Z.json --examples 3

The expected audit output should include a total around `173483` for the current snapshot and nonzero counts for the known issue classes.

Actual result with `.venv/bin/recovery-meeting-ingestion audit-snapshot-quality snapshots/meetings-2026-05-25T143729Z.json --examples 1 --top-sources 10`:

    total_meetings: 173483
    country_aliases: US=>United States, USA=>United States, AU=>Australia, and others
    issue_counts: 843 high_confidence_missing_country, 810 high_confidence_country_conflict, 128 timezone_country_mismatch

Targeted lint and type checks:

    .venv/bin/ruff check app/normalize/location_quality.py app/export/snapshot.py app/cli.py tests/test_location_quality.py tests/test_review_snapshot.py
    All checks passed!

    .venv/bin/mypy app/normalize/location_quality.py app/export/snapshot.py
    Success: no issues found in 2 source files

Full-repository `ruff check` is not clean because of four existing E501 long-line errors in `app/scraping/ca_source_specific.py`. Those lines are unrelated to this change.

## Validation and Acceptance

Acceptance is met when `build_snapshot` fixes the London case in a test, the audit command reports high-confidence issue counts for a real snapshot, and the test suite passes. The user-visible effect is that newly exported snapshots no longer preserve obvious country contradictions, so the mobile app and backend search no longer receive `London, UK, United States` for records that explicitly identify as UK locations.

## Idempotence and Recovery

The normalization is pure and idempotent: running it repeatedly should not keep changing records after the first pass. The audit command is read-only. If a normalization rule is too aggressive, remove or narrow the alias/postcode rule and rerun tests; no database or snapshot files are modified unless an operator explicitly runs `export-snapshot` without `--dry-run`.

## Artifacts and Notes

Manual audit before implementation found:

    TOTAL 173483
    high_confidence_missing_country 843
    high_confidence_country_conflict 798
    timezone_country_mismatch 127

The implementation should treat these numbers as diagnostic, not as hardcoded test expectations, because snapshots change over time.

## Interfaces and Dependencies

In `app/normalize/location_quality.py`, define:

    def normalize_country_name(value: str | None) -> str | None
    def normalize_candidate_location(candidate: CanonicalMeetingCandidate) -> CanonicalMeetingCandidate
    def audit_snapshot_meetings(meetings: Sequence[SnapshotMeeting]) -> LocationQualityAudit

The `LocationQualityAudit` return type should expose machine-readable counts and compact example dictionaries. It should be simple enough for `app/cli.py` to print without duplicating audit logic.

# Reconcile Snapshot Count Drift and Block Bad Location Artifacts

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan follows `PLANS.md` in the repository root.

## Purpose / Big Picture

SoberSpace should only import recovery meeting snapshots when the meeting count and location quality are explainable. The latest local snapshot has 212,151 meetings, while the last imported SoberSpace snapshot had 173,483 meetings. After this work, the operator should know which sources caused the increase, obvious page-artifact rows should be blocked by review flags, and a new snapshot should either be safe to dry-run/import or clearly documented as still blocked.

## Progress

- [x] (2026-05-26T10:28:56Z) Started from an uncommitted location-normalization cleanup and preserved those changes.
- [x] (2026-05-26T10:28:56Z) Confirmed top-source counts differ between `snapshots/meetings-2026-05-25T143729Z.json` and `snapshots/meetings-2026-05-26T101102Z.json`.
- [x] (2026-05-26T10:45:00Z) Produced a source-level count diff between the last imported snapshot and the new local snapshot.
- [x] (2026-05-26T10:57:00Z) Inspected the largest count increases and classified the first group as stale active rows from sources whose latest artifacts contain far fewer records.
- [x] (2026-05-26T11:15:00Z) Added stricter review flags for Wordfence block pages and `Time:` parser-label artifacts.
- [x] (2026-05-26T11:28:00Z) Added timezone reconciliation after country/region disambiguation, including Australian `NT` versus Canadian `NT`.
- [x] (2026-05-26T11:35:00Z) Reprocessed targeted stale NA sources, Australian AA feed artifacts, and artifact sources containing Wordfence/`Time:` rows.
- [x] (2026-05-26T11:50:00Z) Exported and audited replacement snapshot `snapshots/meetings-2026-05-26T113153Z.json`.
- [x] (2026-05-26T11:55:00Z) Decided not to dry-run/import into SoberSpace yet because the count remains 25,297 above the last imported snapshot and the largest remaining source deltas need source-policy review.
- [x] (2026-05-26T12:05:00Z) Reprocessed additional stale NA sources, including North Bay/Calchaqui/Florida and the repeated Ohio BMLT cluster.
- [x] (2026-05-26T12:20:00Z) Fixed address-region parsing that treated street names and directional abbreviations as states (`Washington St`, `E Kentucky Rd`, `St NE`).
- [x] (2026-05-26T12:28:00Z) Exported `snapshots/meetings-2026-05-26T115020Z.json` after the second triage pass.
- [x] (2026-05-26T12:55:00Z) Added persistent `sources.config.snapshot_excluded` handling and excluded duplicate source `aa-16c5e7fd0176`.
- [x] (2026-05-26T13:05:00Z) Blocked collapsed schedule-table rows with oversized display/location fields and reprocessed affected sources.
- [x] (2026-05-26T13:27:00Z) Dry-run validated final snapshot `snapshots/meetings-2026-05-26T122303Z.json` with the SoberSpace importer.

## Surprises & Discoveries

- `na-59444ef38a18`, `na-74bb4b97a659`, and `na-d21377dcf8ed` each contributed 3,638 meetings to the new snapshot, but their latest NA artifact summaries contain 0, 63, and 619 extracted records respectively. These are stale active rows in the local database, not explainable new coverage.
- `aa-08512eb5f89d` and `aa-16c5e7fd0176` each contributed about 2,230 Australian AA rows. Their direct artifacts are successful and current-looking, but they appear to be broad/national feed imports under source IDs with narrower names. This needs source policy/dedupe review rather than silent deletion.
- The snapshot audit examples included Wordfence security block pages being parsed as meetings.
- Australian `NT` rows were normalized to country `Australia` and region `Northern Territory`, but retained `America/Yellowknife` occurrence timezones from the ambiguous region abbreviation. Snapshot normalization now reconciles contradictory occurrence timezones when the country/region pair is known.
- A street named `Victoria Hwy` was being treated as the Australian state of Victoria. The address evidence parser now prefers Australian region tokens in postcode/admin segments and avoids street-address segments.
- A US state/ZIP address was triggering the loose Irish eircode detector. Eircode evidence is now suppressed when the same address has US state/ZIP evidence.
- City/place names that are also country names (`Nederland`, Texas and `Denmark`, Western Australia) were causing false country conflict audit findings. City fields are no longer treated as high-confidence country evidence, and US state/ZIP context suppresses foreign country aliases in address segments.
- Several address lines had street tokens misclassified as admin regions: `Washington St` became Washington, `E Kentucky Rd` became Kentucky, and `St NE` became Nebraska. Region extraction now prioritizes the postal-code segment and ignores street-address segments when choosing an admin region.
- The Ohio NA BMLT area cluster contained many sources with 606 active rows each, while the latest successful artifacts contained 0-61 records. Reprocessing those sources reduced the snapshot by about 9,900 rows.
- `aa-08512eb5f89d` and `aa-16c5e7fd0176` are near-exact duplicates: 2,230 duplicate meetings across 2,222 duplicate location/name keys. This is a remaining source-policy blocker.
- The SoberSpace dry-run surfaced two collapsed schedule-table artifacts that exceeded backend index limits. Generalized review rules now block implausibly large `name`, `venue_name`, `city`, and `address_line1` fields before export.

## Decision Log

- Decision: Do not import any snapshot with an unexplained 38,000-plus meeting increase into SoberSpace.
    Rationale: The downstream importer is idempotent, but a large unexplained count jump can pollute frontend filters and active meeting tables.
    Date/Author: 2026-05-26, Codex.
- Decision: Do not dry-run or import `snapshots/meetings-2026-05-26T113153Z.json` into SoberSpace yet.
    Rationale: Quality is materially cleaner, but the snapshot still has 198,780 meetings versus 173,483 in the last imported snapshot. The remaining largest increases include broad Australian AA feeds and other large source expansions that are not yet classified as intentional.
    Date/Author: 2026-05-26, Codex.

## Outcomes & Retrospective

Implemented the quality cleanup and exported `snapshots/meetings-2026-05-26T113153Z.json`.

Final snapshot:

    active_meetings: 198780
    blocked_by_review: 137
    snapshot_id: 5ef4c465-ac58-4108-b7b4-fc87fe5bcd03
    sha256: 5035909bcd1ed477140a98503ab33523d6c7e6e92ff36a95e959927105cb5477

The audit improved from `20833 timezone_country_mismatch` and `30 high_confidence_country_conflict` to only `6 timezone_country_mismatch` and no country conflicts. The remaining mismatches are NA online rows with no physical address and UTC or foreign timezones.

The count drift improved from +38,668 over the last imported snapshot to +25,297. The largest stale NA artifacts were reconciled, but the remaining count growth is still not safe to import without classifying the top changed sources.

Validation:

    .venv/bin/pytest tests/test_location_quality.py tests/test_review_snapshot.py tests/test_registry.py
    .venv/bin/pytest
    git diff --check

Second triage snapshot:

    path: snapshots/meetings-2026-05-26T115020Z.json
    active_meetings: 184008
    blocked_by_review: 161
    snapshot_id: f5df69b1-d76d-4cfe-96d9-d672ab78851e
    sha256: da2f63feb70308db4bb0746e8283c2b79e24bddc48330df22513568104c1cf17

This reduces the count drift to +10,525 over the last imported snapshot. Snapshot audit remains clean except for 6 NA online timezone mismatches.

Remaining top count increases mostly match current successful artifacts and look like recovered coverage, except the Australian AA duplicate pair:

    aa-04bb97df588a: +2790, current artifact 3108, Boston/Massachusetts recovery
    aa-08512eb5f89d: +2231, current artifact 2231, duplicate Australian national feed
    aa-16c5e7fd0176: +2230, current artifact 2230, duplicate Australian national feed
    aa-8a2226952ff5: +1579, current artifact 1771, Dallas/Texas recovery
    aa-938cab25ed57: +1178, current artifact 1178, Portland/Oregon recovery
    aa-6f246969f596: +1049, current artifact 1099, Missouri recovery

Final dry-run snapshot:

    path: snapshots/meetings-2026-05-26T122303Z.json
    active_meetings: 181627
    blocked_by_review: 172
    snapshot_id: ceb004ab-5e15-4fc9-a09b-b3c73154b7a5
    sha256: cff4d7c93112fb36d8557567ded1dbbb956e9e4894e71c5d05270ed31e5741c3

SoberSpace dry-run:

    command: GOCACHE=/tmp/go-build GOMODCACHE=/tmp/go-mod go run ./cmd/import-recovery-meetings --snapshot /home/michaelroddy/repos/recovery-meeting-ingestion/snapshots/meetings-2026-05-26T122303Z.json --dry-run
    import_run: b288e365-f772-4d06-8856-30a263655f98
    meetings_seen: 181627
    meetings_upserted: 181627
    occurrences_written: 176062
    marked_stale: 23519
    marked_inactive: 0

Final validation:

    .venv/bin/pytest
    git diff --check

No committed SoberSpace import was run in this pass; only the dry-run was executed.

## Context and Orientation

The source of truth for downstream import is a JSON snapshot under `snapshots/`. The last imported SoberSpace snapshot was `snapshots/meetings-2026-05-25T143729Z.json`, with 173,483 meetings. The latest local snapshot is `snapshots/meetings-2026-05-26T101102Z.json`, with 212,151 meetings and 96 records blocked by open review errors. The snapshot audit command is `recovery-meeting-ingestion audit-snapshot-quality <snapshot>`.

Review flags are stored in the ingestion database and represented by `app/review/flags.py`. Snapshot export excludes rows with open error review flags through `CanonicalMeetingRepository.list_active_candidates_for_snapshot`.

## Plan of Work

First, compare source-level meeting counts between the last imported snapshot and the new local snapshot. This identifies the sources responsible for the count increase.

Second, inspect representative records from the largest changed sources and the audit’s top mismatch sources. The goal is to decide whether the increase is caused by intentional source recovery, duplicate source expansion, or page artifacts.

Third, extend review flagging for obvious block-page and boilerplate artifacts, especially examples like Wordfence security pages being parsed as meetings.

Fourth, reprocess affected sources where artifacts can be blocked by the existing raw artifacts. If the issue is stale local database state or duplicate source expansion, document the needed remediation before import.

Finally, export and audit a new snapshot. Only dry-run the SoberSpace importer if the count and quality profile are explainable.

## Concrete Steps

Run all commands from `/home/michaelroddy/repos/recovery-meeting-ingestion`.

Use `jq`, `sort`, `join`, and `awk` to compare source counts. Use `psql postgresql:///recovery_meeting_ingestion_dev` to inspect canonical rows and review flags. Run focused tests after code changes:

    .venv/bin/pytest tests/test_review_snapshot.py tests/test_location_quality.py

Run the full suite if behavior changes affect ingestion or export:

    .venv/bin/pytest

## Validation and Acceptance

Acceptance is met when the largest source-count changes are listed with explanations, newly identified page artifacts receive open error review flags, and the replacement snapshot audit is materially cleaner or explicitly blocked from downstream import with evidence.

## Idempotence and Recovery

All analysis commands are read-only. Reprocessing artifact summaries is safe and idempotent because canonical meetings are upserted by `source_id` and `source_record_id`, and review flags are replaced per source. If a cleanup rule is too broad, revert the rule, rerun the focused tests, and reprocess only the affected source.

## Artifacts and Notes

Known starting point:

    Last imported snapshot: snapshots/meetings-2026-05-25T143729Z.json
    New local snapshot: snapshots/meetings-2026-05-26T101102Z.json
    New local audit: 20833 timezone_country_mismatch, 30 high_confidence_country_conflict

## Interfaces and Dependencies

This plan may extend `app.review.flags.flags_for_candidate(candidate) -> list[ReviewFlag]`. It should preserve the existing review flag contract and use severity `error` only for records that should be excluded from snapshots.

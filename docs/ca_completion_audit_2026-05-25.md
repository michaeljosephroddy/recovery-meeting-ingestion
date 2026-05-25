# CA Completion Audit - 2026-05-25

This audit checked whether CA had any recoverable zero-active sources after the NA completion pass.

## Starting State

- Active CA meetings: 2,336.
- Active CA sources: 79.
- Total CA sources: 123.
- Zero-active CA sources: 44.
- Zero-active by adapter: 21 `playwright_browser`, 23 `unknown`.
- Open CA review flags: 0.
- Previous snapshot: `snapshots/meetings-2026-05-25T113118Z.json`.

## Audit Results

`audit-zero-sources --fellowship ca` inspected 21 zero-active browser sources and produced 8 curated retry candidates.

Bucket counts:

- `blocked_or_captcha`: 4
- `low_signal`: 4
- `parser_gap_candidate`: 3
- `possible_missed_structured_feed`: 3
- `meeting_keywords_only`: 3
- `dead_or_error_page`: 2
- `possible_pdf_or_printable`: 1
- `possible_embed_or_calendar`: 1

The 23 zero-active `unknown` rows are all CA world-service listing pages. All 23 are shadowed by local CA source rows through the normal CA full-scrape skip logic, so they are not additional local recovery targets.

## Retry Results

The curated retry ran against 8 source ids:

- `ca-07c6c8d379bd` New Jersey: recovered 25 records and persisted 25 canonical CA meetings.
- `ca-200708853eaf` Nashville: completed with 0 records.
- `ca-609577b509b9` Central UK: completed with 0 records.
- `ca-c96cd333bd23` San Fernando Valley: completed with 0 records.
- `ca-d7d0c4eae08f` Columbus: completed with 0 records.
- `ca-e4d3d7f0476f` Wisconsin: completed with 0 records.
- `ca-f60993c27baf` Quebec: completed with 0 records.
- `ca-f6c1ff14a8cb` Texas: completed with 0 records.

## Final State

- Active CA meetings: 2,361.
- Active CA sources: 80.
- Total CA sources: 123.
- Zero-active CA sources: 43.
- Zero-active by adapter: 20 `playwright_browser`, 23 shadowed `unknown` world-service listing rows.
- Open CA review flags: 0.
- New snapshot: `snapshots/meetings-2026-05-25T120801Z.json`.
- Snapshot counts: AA 96,583; CA 2,361; NA 74,325; total 173,269.

## Downstream Import

The refreshed snapshot was dry-run validated and then imported into SoberSpace.

- Import run: `08dce78d-16d2-4fbd-a220-a2edc74cd841`.
- Snapshot SHA-256: `e1acb23d11b25c991053264f75fc79996d100079e44627264ccb6fad13927eae`.
- Meetings seen/upserted: 173,269.
- Occurrences written: 162,352.
- Marked stale: 858.
- Marked inactive: 0.

# CA Remaining Source Recovery - 2026-05-25

This pass recovered CA meetings from zero-active local source rows that still had public schedule data after the CA completion audit.

## Recovered Sources

- Quebec `ca-f60993c27baf`: 84 active meetings.
- Texas `ca-f6c1ff14a8cb`: 44 active meetings.
- Denmark `ca-63a0c6bbe7d2`: 25 active meetings.
- Wisconsin `ca-e4d3d7f0476f`: 20 active meetings.
- Nashville `ca-200708853eaf`: 10 active meetings.
- Columbus `ca-d7d0c4eae08f`: 9 active meetings.
- Greece `ca-2915b40b65f2`: 8 active meetings.
- Oklahoma `ca-60973398a3f3`: 7 active meetings.
- Maritimes `ca-4b3b7087b949`: 6 active meetings.
- Russia `ca-e2f77889edc7`: 1 active meeting.

## Remaining Local CA Gaps

- Hong Kong `ca-35a80b91e362`: request timed out from this environment.
- Netherlands `ca-323a95f13ea7`: returned a network parental-control block page.
- CyberSerenity `ca-515a0089a544`: live site, but no dated weekly meeting schedule found.
- Central UK `ca-609577b509b9`: rendered a loading shell with no extractable schedule.
- Connecticut `ca-041da33d75c7`: live site, but no public meeting list found.
- Indiana `ca-02679930ead3`: returned a network parental-control block page.
- Maine old Webs site `ca-e2760999c192`: DNS lookup failed.
- San Diego `ca-a881e4c39ef0`: returned a network parental-control block page.
- SFVCA `ca-c96cd333bd23`: Airtable directory embed did not expose public rows through HTML/API inspection.
- North Texas `ca-23b0bd1f769e`: DNS lookup failed.

The 23 zero-active `unknown` CA rows are still shadowed CA world-service listing pages, not independent local scrape targets under the current CA strategy.

## Final State

- Active CA meetings: 2,575.
- Active CA sources: 90.
- Open CA review flags: 0.
- Snapshot: `snapshots/meetings-2026-05-25T125615Z.json`.
- Snapshot counts: AA 96,583; CA 2,575; NA 74,325; total 173,483.

## Downstream Import

The refreshed snapshot was dry-run validated and then imported into SoberSpace.

- Import run: `fe803b9e-d3e1-4c87-8ce7-d141870f0347`.
- Snapshot SHA-256: `597268fbbac50fbe81a86408e56f22b893be09047210a71b8fab699b5aaaff58`.
- Meetings seen/upserted: 173,483.
- Occurrences written: 162,572.
- Marked stale: 0.
- Marked inactive: 858.

## Refresh Behavior

Routine refreshes should scrape AA, CA, and NA source sets, then export one combined snapshot. Running the fellowships as separate scrape jobs makes failures easier to isolate:

```bash
PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers .venv/bin/python -m app.cli scrape-all --fellowship aa --no-dry-run --concurrency 6
PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers .venv/bin/python -m app.cli scrape-all --fellowship ca --no-dry-run --concurrency 6
PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers .venv/bin/python -m app.cli scrape-all --fellowship na --no-dry-run --concurrency 6
.venv/bin/python -m app.cli export-snapshot --no-dry-run
```

When a source scrape succeeds, new source records are upserted and previously active meetings from that same source that are no longer present are marked missing/stale. A blocked, dead, or parser-broken source should be reviewed rather than treated as authoritative evidence that all of its meetings were removed.

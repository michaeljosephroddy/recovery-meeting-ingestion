# EC2 Operations

Run this service as a separate worker from the SoberSpace API.

Recommended production flow:

```text
systemd timer
  -> discover-sources
  -> scrape-all
  -> export-snapshot
  -> publish snapshot artifact
```

Minimum environment:

```bash
DATABASE_URL=postgresql://...
USER_AGENT="SoberSpaceRecoveryMeetingIngestion/1.0 ops@soberspace.app"
SNAPSHOT_OUTPUT_DIR=/var/lib/recovery-meeting-ingestion/snapshots
SCRAPE_ARTIFACT_DIR=/var/lib/recovery-meeting-ingestion/scrape_artifacts
DEFAULT_RATE_LIMIT_SECONDS=1
```

Example service command:

```bash
.venv/bin/python -m app.cli scrape-all --no-dry-run --output-dir "$SCRAPE_ARTIFACT_DIR"
.venv/bin/python -m app.cli export-snapshot --no-dry-run
```

Use CloudWatch or journald forwarding for logs. Alert when import runs fail, a snapshot has zero
meetings, or review flags spike.

Install Playwright Chromium on the worker image before running browser scraping:

```bash
.venv/bin/pip install -e ".[playwright]"
.venv/bin/playwright install chromium
```

For incident debugging, run:

```bash
.venv/bin/python -m app.cli debug-scrape-source --source-id SOURCE_ID --output-dir "$SCRAPE_ARTIFACT_DIR/debug"
```

Inspect `summary.json`, rendered page HTML, action traces, extraction traces, and screenshots in the
debug artifact directory.

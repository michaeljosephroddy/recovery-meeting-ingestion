# EC2 Operations

Run this service as a separate worker from the SoberSpace API.

Recommended production flow:

```text
systemd timer
  -> discover-sources
  -> ingest-all
  -> export-snapshot
  -> publish snapshot artifact
```

Minimum environment:

```bash
DATABASE_URL=postgresql://...
USER_AGENT="SoberSpaceRecoveryMeetingIngestion/1.0 ops@soberspace.app"
SNAPSHOT_OUTPUT_DIR=/var/lib/recovery-meeting-ingestion/snapshots
DEFAULT_RATE_LIMIT_SECONDS=1
```

Example service command:

```bash
.venv/bin/python -m app.cli ingest-all --no-dry-run
.venv/bin/python -m app.cli export-snapshot --no-dry-run
```

Use CloudWatch or journald forwarding for logs. Alert when import runs fail, a snapshot has zero
meetings, or review flags spike.


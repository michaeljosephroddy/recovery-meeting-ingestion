# SoberSpace Integration

The ingestion service should not write directly to SoberSpace production app tables.

Handoff contract:

```text
recovery-meeting-ingestion Postgres
  -> reviewed JSON snapshot
  -> S3 or shared artifact location
  -> SoberSpace import command
  -> SoberSpace recovery meeting tables
```

The SoberSpace API should import snapshots idempotently using:

```text
fellowship + source_id + source_record_id
```

Do not map these records into user-created `meetups` directly. Recovery meetings are external,
recurring, and source-attributed. SoberSpace should use dedicated recovery meeting tables and keep
raw payloads out of the app database.

Importer requirements:

- Validate `schema_version`.
- Upsert meetings and weekly occurrences.
- Mark missing records stale before inactive.
- Reject snapshots with unexpected zero-record drops unless manually approved.
- Store snapshot path and import run metadata for rollback.


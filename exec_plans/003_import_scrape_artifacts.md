# Import Scrape Artifacts Into Durable Storage

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

## Purpose / Big Picture

The repository already has useful browser scrape artifacts under `scrape_artifacts/`, but the local Postgres database only contains a tiny amount of persisted meeting data. Add an artifact replay path so existing scrape summaries can be converted into raw records, canonical candidates, review flags, and import runs without re-crawling live recovery meeting websites.

After this change, an operator can run:

    python -m app.cli import-artifacts scrape_artifacts/smoke-20260501T111620Z

and first see dry-run totals, then re-run with `--no-dry-run` to persist the artifacts.

## Progress

- [x] Added this ExecPlan.
- [x] Added an artifact summary importer for scrape `summary.json` files and controlled smoke reports.
- [x] Added `import-artifacts` CLI command with dry-run default and optional source filtering.
- [x] Added a reusable raw-record ingestion helper so artifact replay uses the same normalization/review guardrails as scrape ingestion.
- [x] Added CLI coverage for dry-run artifact replay.

## Surprises & Discoveries

- Observation: The controlled smoke reports contain source metadata, so replay can reconstruct sources even if the DB does not already contain them.
  Evidence: `controlled_smoke_report.json` source rows include source id, fellowship, name, URL, country, region, and timezone.

- Observation: Individual `summary.json` files contain extracted payloads with embedded extraction metadata, but not always full source metadata.
  Evidence: Per-source summaries include `source_id`, `source_url`, pages, and extracted payloads; the controlled report is needed for better labels and timezone.

## Decision Log

- Decision: Make artifact import dry-run by default.
  Rationale: Artifact replay can write thousands of canonical candidates, and operators should inspect counts before mutating local Postgres.
  Date/Author: 2026-05-21 / Codex

- Decision: Reconstruct `RawMeeting` records from extracted payloads instead of re-reading rendered HTML.
  Rationale: The summaries already preserve extracted payloads, confidence metadata, and source page URLs, which is enough to run normalization/review without re-crawling.
  Date/Author: 2026-05-21 / Codex

## Outcomes & Retrospective

Artifact replay is implemented as a development/operator tool. It does not replace live scraping; it gives the team a fast loop for improving normalization, dedupe, review flags, and snapshot export using existing captured evidence.

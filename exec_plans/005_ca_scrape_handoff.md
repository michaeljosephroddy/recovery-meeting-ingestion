# CA Scrape Handoff

Date: 2026-05-21

## Current State

The CA scraper cleanup and targeted meeting-page work is implemented but not committed in this workspace yet.

Key implementation points:

- CA source cleanup removed invalid/noise local source URLs.
- CA discovery was rerun and currently has 123 scrapeable CA sources.
- Browser crawler now prioritizes meeting pages first, using common English and non-English meeting paths.
- Multilingual meeting vocabulary was added for URLs, page scoring, weekdays, and text extraction.
- Direct CA world-service listing pages are supported, including Mexico.
- Wix dynamic collection pagination is supported, which fixes Ireland beyond the rendered 100-record cap.
- Paragraph/day-section extraction was improved for non-English pages like Poland.
- Artifact import tooling was added for importing scrape artifacts into ingest flow.

## Latest Validation

Passed:

- `.venv/bin/ruff check app tests`
- `.venv/bin/mypy app`
- `.venv/bin/pytest -q`

Latest full test result:

- `79 passed, 10 skipped`

## Focused Source Checks

Known working examples:

- Ireland: `ca-23bc07bc85b3`, `https://www.caireland.live`
  - Now extracts `142/142` records via Wix Cloud Data pagination.
- Mexico: `ca-0812964d4a0a`, `https://ca.org/meetings/mexico/`
  - Extracts `3` direct listing records from the CA world-service page.
- Poland: `ca-18329a6abe7c`, `https://ca-polska.org`
  - Routes to `/spotkania/` and extracts `11` records.

## CA-Wide Dry Run

Latest dry run command:

```bash
PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers \
  .venv/bin/python -m app.cli scrape-all \
  --fellowship ca \
  --max-pages-per-source 6 \
  --output-dir scrape_artifacts/ca-wide-dry-run-20260521
```

Dry run summary:

- Sources checked: `123`
- Succeeded: `119`
- Failed: `4`
- Sources with records: `63`
- Zero-record successful sources: `56`
- Total records extracted: `1,416`
- Artifact directory: `scrape_artifacts/ca-wide-dry-run-20260521`

High-yield working sources:

- Ireland: `142`
- UK: `141`
- London: `109`
- CA South West UK: `75`
- Los Angeles: `50`
- Arizona: `47`

## Known Failures

These need URL correction or source-specific handling:

- `ca-23b0bd1f769e` - `http://www.northtexasca.com/`
  - DNS failure: `ERR_NAME_NOT_RESOLVED`
- `ca-35a80b91e362` - `http://cahongkong.com/`
  - Redirect loop: `ERR_TOO_MANY_REDIRECTS`
- `ca-6e8cc57bd9cf` - `https://cautah.org`
  - Timeout loading page.
- `ca-e2760999c192` - `http://camaine-com.webs.com/`
  - DNS failure: `ERR_NAME_NOT_RESOLVED`

## Next Step

Do not run the real import yet.

Resume from triaging the dry-run artifacts:

1. Inspect zero-yield sources with high page scores and likely meeting pages.
2. Separate true no-meeting/world-service contact-only pages from parser gaps.
3. Prioritize TSML/dynamic-list extraction gaps, especially pages that score `0.9+` but extract `0`.
4. Rerun the CA dry run after fixes.
5. Only then run the non-dry import.

Useful artifact triage target:

```bash
scrape_artifacts/ca-wide-dry-run-20260521
```


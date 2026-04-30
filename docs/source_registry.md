# Source Registry

Local development should use a dedicated database for ingestion state:

```bash
createdb recovery_meeting_ingestion_dev
export DATABASE_URL=postgresql:///recovery_meeting_ingestion_dev
alembic upgrade head
```

Do not point the ingestion service at the SoberSpace app database. Meeting data should move to
SoberSpace through reviewed snapshots or a later import command.

## Discovering World-Service Sources

The discovery command can fetch the official AA, CA, and NA world-service pages and store source
registry rows in the ingestion database:

```bash
python -m app.cli discover-sources --fellowship aa --no-dry-run
python -m app.cli discover-sources --fellowship ca --no-dry-run
python -m app.cli discover-sources --fellowship na --no-dry-run
```

After discovery, classify the local sources so `ingest-all` knows which adapter to use:

```bash
python -m app.cli classify-sources --fellowship aa --no-dry-run
python -m app.cli classify-sources --fellowship ca --no-dry-run
python -m app.cli classify-sources --fellowship na --no-dry-run
```

Classification probes each local site for structured Meeting Guide feeds and BMLT JSON endpoints.
When it finds one, it updates the source registry with the right adapter and feed endpoint. If it
only finds a meeting page, PDF, phone number, or search form that needs source-specific selectors, it
marks the source for manual review instead of pretending arbitrary HTML is safe to ingest.
By default it skips sources that already have an ingest adapter; use `--include-configured` or
`--source-id` when you intentionally want to re-probe an existing configured source.

For a small live smoke test, add `--max-locations`:

```bash
python -m app.cli discover-sources --fellowship ca --max-locations 5 --dry-run
python -m app.cli discover-sources --fellowship na --max-locations 5 --dry-run
```

AA discovery starts at `https://www.aa.org/find-aa/world`, requests rendered AA location-listing
views, and collects local A.A. office/intergroup websites or phonelines.

CA discovery starts at `https://ca.org/meetings/`, records CA country/online listing pages, then
follows those pages to collect external local CA area websites.

NA discovery starts at `https://na.org/meetingsearch/find-na/`, uses the NA locator AJAX endpoint to
bootstrap the country/state index, then requests each listing bucket to collect local NA websites and
phonelines. `--max-locations` limits those listing buckets; omit it for the full discovered index.

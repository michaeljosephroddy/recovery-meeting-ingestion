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

After discovery, scrape the local sources. The default workflow uses Playwright to visit local
service-body websites, find likely meeting pages, interact with common controls, extract rendered
meeting-looking records, and route uncertain records to review:

```bash
python -m app.cli scrape-all --fellowship aa --no-dry-run
python -m app.cli scrape-all --fellowship ca --no-dry-run
python -m app.cli scrape-all --fellowship na --no-dry-run
```

`classify-sources` still exists as a legacy inspection command for structured Meeting Guide or BMLT
feeds, but it is no longer the default path. Use it only when you intentionally want to inspect a
site for feed-style integrations.

## Interactive Local Sites

Use `adapter_type=playwright_browser` for local service-body sites that require JavaScript,
clicking, form fields, or other browser interaction before the meeting rows exist in the DOM.
Install the optional browser dependency and Chromium runtime before running these sources:

```bash
pip install -e ".[playwright]"
playwright install chromium
```

The browser scraper first performs `config.browser.actions`, then tries low-risk heuristic actions
such as meeting/list buttons, accordion expansion, load-more controls, and simple search forms seeded
from source region or country. It captures rendered HTML and parses it with Beautiful Soup. Configured
selectors are used first, then heuristic extraction from tables, repeated cards/lists, and text
blocks. Example source config:

If a rendered page exposes a Crouton/BMLT `root_server` in its JavaScript and the generic rendered
HTML extractor finds no meeting rows, the scraper falls back to the discovered BMLT JSON endpoint.
When the page includes `service_body` filters, those filters are included so the fallback does not
pull the entire regional BMLT server by mistake.

```json
{
  "timezone": "Europe/Dublin",
  "browser": {
    "timeout_ms": 20000,
    "wait_until": "networkidle",
    "actions": [
      {"type": "fill", "selector": "input[name='city']", "value": "Dublin"},
      {"type": "select_option", "selector": "select[name='day']", "label": "Monday"},
      {"type": "click", "selector": "button[type='submit']", "wait_for": ".meeting"}
    ],
    "wait_for_selector": ".meeting"
  },
  "selectors": {
    "row": ".meeting",
    "source_record_id": ".meeting::attr(data-id)",
    "name": ".name",
    "day": ".day",
    "time": ".time",
    "venue_name": ".venue",
    "address_line1": ".address",
    "city": ".city",
    "formats": ".formats"
  }
}
```

Supported browser action types are `fill`, `click`, `select_option`, `press`, `check`, `uncheck`,
`wait_for_selector`, `wait_for_timeout`, and `wait_for_load_state`. Use `http://localhost:...` or
another reachable URL when testing against a locally running site.

Useful scrape commands:

```bash
python -m app.cli scrape-source --source-id aa-example --dry-run
python -m app.cli scrape-source --source-id aa-example --max-pages 10 --max-depth 1 --no-dry-run
python -m app.cli debug-scrape-source --source-id aa-example --output-dir scrape_artifacts/debug
```

`debug-scrape-source` always writes artifacts. Normal scrape commands write artifacts by default
under `scrape_artifacts/`; use `--no-save-artifacts` when you only want the terminal summary.
Artifacts include a summary JSON file, rendered HTML per visited page, page/action/extraction JSON,
and screenshots when Playwright can capture them.

Confidence metadata is embedded in each scraped raw payload under `extraction`. Records with
confidence below `0.75` create review flags. Records below `0.45` are retained as raw/evidence data
but are not normalized into canonical meeting candidates by default.

For a small live smoke test, add `--max-locations`:

```bash
python -m app.cli discover-sources --fellowship ca --max-locations 5 --dry-run
python -m app.cli discover-sources --fellowship na --max-locations 5 --dry-run
```

AA discovery starts at `https://www.aa.org/find-aa/world`, reads the world-page location filters,
then requests each U.S. state, Canadian province, and international country filter page. It collects
local A.A. office/intergroup websites or phonelines from those listing results. `--max-locations`
limits how many AA filter pages are fetched; omit it for the full discovered filter queue.

CA discovery starts at `https://ca.org/meetings/`, records CA country/online listing pages, then
follows CA world-service listing pages recursively to collect external local CA area websites. When a
CA listing redirects to an external local service-body site, discovery records that site and stops at
that boundary instead of crawling the local site's navigation as more source registry rows.

NA discovery starts at `https://na.org/meetingsearch/find-na/`, uses the NA locator AJAX endpoint to
bootstrap the country/state index, then requests each listing bucket to collect local NA websites and
phonelines. `--max-locations` limits those listing buckets; omit it for the full discovered index.

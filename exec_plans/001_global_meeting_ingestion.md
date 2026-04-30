# Build the SoberSpace Global Meeting Ingestion Service

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This repository was created as a separate project from the SoberSpace API. The original planning guidance came from `/home/michaelroddy/repos/project_radeon/PLANS.md`, but this file is self-contained and can be followed without reading that source document.

## Purpose / Big Picture

SoberSpace needs a curated store of recovery fellowship meetings from around the world. After this work is complete, an operator can run a Python ingestion service that discovers official meeting sources, imports meeting records, normalizes them into a common schema, flags suspicious or sensitive data for review, and publishes a clean snapshot that the SoberSpace app can consume.

The first useful outcome is not a claim of complete global coverage. The first useful outcome is an auditable pipeline that can discover AA, CA, and NA local service sources from world-service locator pages, ingest structured AA Meeting Guide feeds and other local source data through adapters, and show exactly which sources succeeded, failed, or require manual review.

## Progress

- [x] (2026-04-30 20:55Z) Created the initial ExecPlan for a new `recovery-meeting-ingestion` repository.
- [x] (2026-04-30 21:41Z) Updated the ExecPlan to treat the AA World Services world finder as an AA source discovery layer before local-source ingestion.
- [x] (2026-04-30 21:53Z) Clarified that local development should use a separate Postgres database for ingestion state, distinct from the SoberSpace app database.
- [x] (2026-04-30 22:04Z) Initialized the Python project with `pyproject.toml`, package layout, local dev docs, linting, type-checking, and fixture-backed tests.
- [x] (2026-04-30 22:04Z) Implemented initial canonical meeting models, source registry models, review flags, snapshot export models, and Alembic-wired ingestion schema.
- [x] (2026-04-30 22:04Z) Added first-pass fixture-backed AA, CA, and NA world-service discovery parsers plus Meeting Guide and BMLT normalization adapters.
- [x] (2026-04-30 22:08Z) Added stable source URL normalization and IDs, candidate-to-source conversion, Postgres source upsert/list/count repository methods, and `discover-sources` fixture/live parse flows with dry-run or persist behavior.
- [x] (2026-04-30 22:11Z) Added an opt-in local Postgres source repository integration test path, source lookup, raw meeting persistence, and real `ingest-source` dry-run flows for Meeting Guide and BMLT fixtures.
- [x] (2026-04-30 22:15Z) Ran local Postgres migrations and `RUN_DB_TESTS=1` repository tests, added import run persistence, and verified non-dry-run Meeting Guide fixture ingestion is idempotent for unchanged raw records.
- [x] (2026-04-30 22:19Z) Added canonical meeting and occurrence persistence, wired non-dry-run `ingest-source` to upsert normalized candidates, and verified local Postgres canonical repository integration tests.
- [x] (2026-04-30 22:25Z) Added review flag persistence and DB-backed snapshot export, verified `export-snapshot` reads active canonical meetings from local Postgres, and wrote a test snapshot to `/tmp`.
- [x] (2026-04-30 22:29Z) Hardened structured Meeting Guide and BMLT adapter fetch paths with shared JSON-array fetching, transient retry behavior, clearer adapter exceptions, injectable HTTP transports, and MockTransport coverage.
- [x] (2026-04-30 22:42Z) Added opt-in live smoke tests for configured AA Meeting Guide and BMLT endpoints using `RUN_LIVE_TESTS`, `LIVE_MEETING_GUIDE_URL`, and `LIVE_BMLT_ROOT_URL`.
- [x] (2026-04-30 22:37Z) Implemented configured static HTML and form-backed HTTP adapters, optional PDF and Playwright adapter foundations, HTML fixture ingestion, and fallback adapter tests.
- [x] (2026-04-30 22:42Z) Implemented dedupe candidate detection, source-drop review flags, stale/inactive missing-run tracking, latest snapshot file publication, and snapshot DB records.
- [x] (2026-04-30 22:42Z) Implemented registry-backed `ingest-all` and added EC2 operations plus SoberSpace snapshot handoff documentation.
- [x] (2026-04-30 23:18Z) Replaced generic CA/NA world-page parsing with source-specific automation: CA follows CA meeting listing pages to external local area sites, and NA uses the official locator AJAX endpoint to enumerate country/state buckets, local NA websites, and phonelines.
- [x] (2026-05-01 00:24Z) Replaced generic AA world-page link scraping with source-specific parsing of AA rendered location-listing views, including local websites and phone-only resources.
- [x] (2026-05-01 00:47Z) Added `classify-sources` to probe discovered local sites for Meeting Guide feeds and BMLT endpoints, persist adapter/feed configuration, and mark forms, PDFs, phone-only sources, and unsupported meeting pages for manual review.

## Surprises & Discoveries

- Observation: CA and NA world-service sites should be treated as source discovery layers, not complete meeting databases.
    Evidence: NA World Services states that it does not keep a database of in-person NA meetings and directs users to local NA websites and phonelines. CA World Services meeting pages similarly route users to local country or area resources rather than exposing a single global meeting API.

- Observation: The Code4Recovery repository is a feed specification for AA Meeting Guide-compatible data, not one global API endpoint containing every AA meeting.
    Evidence: The spec describes how local entities expose JSON feeds with fields such as `name`, `slug`, `day`, `time`, `address`, `city`, `country`, `conference_url`, and `updated`.

- Observation: The AA World Services "Find A.A. Near You (World)" page should also be treated as a source discovery layer.
    Evidence: The page states that the website does not contain a meeting finder and directs users to contact listed A.A. resources for meeting lists in each location and surrounding area.

- Observation: The NA in-person locator exposes the same local website and phoneline data through a WordPress plugin AJAX endpoint used by the browser.
    Evidence: The page posts to `https://na.org/wp-content/plugins/meetings-finder/ajax.php` with `action=search` for the location index and `action=listings` for each country/state bucket.

- Observation: The AA world finder is a Drupal Views page whose local resources are present in rendered location-listing views after a location query parameter is supplied.
    Evidence: The page exposes `locations_listing` views and GET requests such as `/find-aa/world?state=CA` render `.area-loc-item` entries with office names, websites, addresses, and phone numbers.

## Decision Log

- Decision: Build this as a Python ingestion service with source-specific adapters rather than one generic web crawler.
    Rationale: CA and NA data lives behind many different local sites, forms, maps, plugins, PDFs, and APIs. Source-specific adapters let the system be tested, debugged, rate-limited, and permission-reviewed per source.
    Date/Author: 2026-04-30 / Codex

- Decision: Use Postgres with PostGIS as the durable store.
    Rationale: The system needs source registry records, raw imports, normalized meetings, geocoded coordinates, deduplication state, review flags, run history, and versioned exports. PostGIS also supports future "meetings near me" search.
    Date/Author: 2026-04-30 / Codex

- Decision: Use a separate Postgres database for ingestion state in local development and production.
    Rationale: The ingestion service stores raw payloads, parser state, review flags, source history, and run logs that should remain isolated from the SoberSpace app database. In local development this can be a separate database on the same local Postgres server, for example `recovery_meeting_ingestion_dev`, with its own `DATABASE_URL`.
    Date/Author: 2026-04-30 / Codex

- Decision: Use HTTP-first scraping with Playwright only as a fallback.
    Rationale: Direct HTTP requests to feeds, JSON endpoints, and form backends are faster, cheaper, easier to test, and less brittle than browser automation. Playwright is still necessary for JavaScript-only meeting finders.
    Date/Author: 2026-04-30 / Codex

- Decision: Publish snapshots to SoberSpace instead of letting the scraper directly mutate live app tables.
    Rationale: Snapshot publishing creates an audit boundary, supports rollback, and allows manual review before questionable data is exposed to users.
    Date/Author: 2026-04-30 / Codex

- Decision: Discover AA sources from the official AA World Services location listing before relying on Meeting Guide feeds.
    Rationale: The AA world page lists local resources for United States, Canada, and international locations, but does not itself expose all meeting records. Those local resources should become source registry rows, then the classifier can identify Meeting Guide feeds, static pages, forms, PDFs, or manual-review sources.
    Date/Author: 2026-04-30 / Codex

- Decision: Classify local sites before ingestion and prefer structured feeds over generic scraping.
    Rationale: Local recovery websites vary widely. Automatically ingesting arbitrary HTML would create a high risk of bad meeting data. Probing for Meeting Guide and BMLT gives safe extraction where structured data exists; everything else is marked for review until source-specific selectors or request config are added.
    Date/Author: 2026-05-01 / Codex

## Outcomes & Retrospective

The repository now has an installable Python project skeleton with strict lint/type/test tooling. The first implementation slice includes canonical meeting models, source registry models, a Postgres/Alembic schema, AA/CA/NA discovery parsers that work against saved HTML fixtures, Meeting Guide and BMLT normalization against saved JSON fixtures, basic review flags, and JSON snapshot construction. Live crawling, durable repository writes, deduplication, geocoding, full review workflows, and SoberSpace import integration remain future milestones.

## Context and Orientation

This is a new repository intended to live at `~/repos/recovery-meeting-ingestion`. It is separate from the Go SoberSpace API repository. The Go API can later import meeting snapshots produced by this project, but this project should not depend on the Go API during its first implementation.

Local development should use its own Postgres database for this service instead of reusing the SoberSpace app database. A typical local setup is one Postgres server with separate databases:

    project_radeon_dev
    recovery_meeting_ingestion_dev

The ingestion service should point `DATABASE_URL` at `recovery_meeting_ingestion_dev`. The SoberSpace API should continue to point at its app database and should receive meeting data only through exported snapshots or a later import command.

A "source" means a website, feed, API endpoint, or document that may contain meeting information or links to local service bodies. A "source registry" is the internal database table that stores each known source, its fellowship, country, URL, adapter type, permission status, and last import status.

An "adapter" means a Python class that knows how to fetch and parse one kind of source. Examples include an AA Meeting Guide JSON feed adapter, a BMLT API adapter, a static HTML table adapter, a PDF adapter, and a Playwright browser adapter. BMLT means "Basic Meeting List Toolbox", a meeting-listing system used by many NA and some other fellowship sites.

A "canonical meeting" means a normalized internal record with common fields regardless of where the data came from. For example, AA may call a location field `location`, a local CA site may show it as table text, and a PDF may format it as a block of lines. The canonical model turns all of those into fields such as `name`, `fellowship`, `meeting_type`, `day_of_week`, `start_time_local`, `timezone`, `address`, `country`, `latitude`, `longitude`, `source_url`, and `last_seen_at`.

The system must distinguish source discovery from meeting ingestion. For AA, CA, and NA, the world-service sites mainly help find local service bodies. The local service bodies are usually where actual meeting records live. For AA, many local entities expose Meeting Guide-compatible JSON feeds that can be consumed directly once their feed URLs are known.

## Plan of Work

Create a Python 3.12 project using `pyproject.toml`. Use `uv` if available for local dependency management, but keep commands compatible with plain `python -m venv` and `pip` so a novice can run the project without knowing `uv`.

Create the following repository layout:

    app/
      cli.py
      config.py
      logging.py
      sources/
        registry.py
        aa_world_services.py
        aa_feed_registry.py
        ca_world_services.py
        na_world_services.py
      adapters/
        base.py
        meeting_guide.py
        bmlt.py
        static_html.py
        form_http.py
        pdf.py
        playwright_browser.py
      normalize/
        canonical.py
        schedule.py
        address.py
        timezone.py
        dedupe.py
      storage/
        db.py
        migrations.py
        repositories.py
      review/
        flags.py
        reports.py
      export/
        snapshot.py
    migrations/
    tests/
    docs/
      data_policy.md
      source_registry.md

The first implementation should provide a command-line interface. The command-line interface is the easiest way to prove that the ingestion service works before adding a scheduler or an admin UI. The CLI should expose commands named `discover-sources`, `ingest-source`, `ingest-all`, `export-snapshot`, and `report`.

The canonical schema should be implemented before any source-specific adapter. This prevents each scraper from inventing its own output shape. The schema should use Pydantic models for validation at the application boundary and Postgres tables for durable state.

The source registry should be implemented before broad crawling. Each source row should store the source URL, fellowship, country, region, source type, adapter type, permission status, last successful run, failure count, and whether browser automation is required.

AA ingestion should have two stages, similar to CA and NA. The first stage visits the official AA World Services page at `https://www.aa.org/find-aa/world` to collect local A.A. resources for United States, Canada, and international locations. Those outputs become source registry rows. Do not assume that the AA World Services page itself contains all meetings. The second stage classifies and ingests each local AA source.

AA local-source ingestion should prefer Meeting Guide-compatible JSON feeds when the classifier finds them. The Code4Recovery spec describes a JSON array of meeting objects. Important fields include `name`, `slug`, `day`, `time`, `end_time`, `timezone`, `location`, `group`, `notes`, `url`, `types`, `address`, `city`, `state`, `postal_code`, `country`, `conference_url`, `conference_url_notes`, `conference_phone`, and `updated`. The implementation should accept missing optional fields, but it must require enough information to identify the meeting and its source. At minimum, each AA record must have a source feed URL, a stable source key such as `slug`, and either physical location data or online meeting data.

CA ingestion should have two stages. The first stage crawls the CA World Services meetings pages to collect country pages, local area pages, local service websites, phone lines, and meeting finder URLs. Those outputs become source registry rows. The second stage classifies and ingests each local CA site. Do not assume that the CA World Services page itself contains all meetings.

NA ingestion should also have two stages. The first stage uses the NA World Services in-person meeting locator at `https://na.org/meetingsearch/find-na/` to discover local NA service websites and phonelines. Since the locator is location-based, discovery should use a seed list of countries, country centroids, and major cities rather than only country names. The second stage classifies and ingests each local NA site. Many NA sites may expose BMLT endpoints, and those should use the BMLT adapter instead of HTML scraping.

For form-based local sites, inspect the network request used by the form before reaching for browser automation. If the form submits to a JSON endpoint, an AJAX endpoint, or a predictable query URL, implement a `FormHttpAdapter`. Use `PlaywrightBrowserAdapter` only when results are genuinely unavailable through normal HTTP.

For PDF meeting lists, implement a `PdfAdapter` only after the canonical schema and HTML adapters exist. PDF extraction is noisy and should always produce review flags unless the source has stable formatting and tests.

The review layer must block questionable output from automatic publication. It should create review flags when a meeting loses its address, changes country, loses online connection info, gains possible personal contact information, cannot resolve a timezone, fails geocoding, or when a source drops more than 20 percent of its previous active meetings in one run.

The export layer should produce a versioned JSON snapshot first. A later milestone may add direct Postgres export or an admin import endpoint in the Go API. The snapshot should include only safe canonical fields and should not include raw payloads, personal contact details, or unreviewed sensitive online credentials.

## Concrete Steps

Begin in the repository root:

    cd ~/repos/recovery-meeting-ingestion

Create the Python project metadata in `pyproject.toml`. The package name should be `recovery-meeting-ingestion`, and the import package should be `recovery_meeting_ingestion`. Require Python 3.12 or newer. Add runtime dependencies for `httpx`, `selectolax`, `pydantic`, `pydantic-settings`, `psycopg`, `alembic`, `tenacity`, `structlog`, `python-dateutil`, `rapidfuzz`, `typer`, and `rich`. Add optional dependencies for `playwright`, `pypdf`, and geocoding providers. Add development dependencies for `pytest`, `pytest-asyncio`, `ruff`, and `mypy`.

Create `app/config.py` with a settings model that reads these environment variables:

    DATABASE_URL
    LOG_LEVEL
    USER_AGENT
    DEFAULT_RATE_LIMIT_SECONDS
    SNAPSHOT_OUTPUT_DIR
    GEOCODER_PROVIDER
    GEOCODER_API_KEY

Document local database setup in `README.md` or `docs/source_registry.md`. The recommended local development database URL should be:

    DATABASE_URL=postgresql:///recovery_meeting_ingestion_dev

The documentation should include setup commands equivalent to:

    createdb recovery_meeting_ingestion_dev
    alembic upgrade head

Create `app/adapters/base.py` with three types. `RawMeeting` represents an untrusted source record. `CanonicalMeetingCandidate` represents a normalized candidate before deduplication and review. `SourceAdapter` is an abstract base class with `fetch` and `normalize` methods. The interface should be:

    class SourceAdapter(Protocol):
        source: Source

        async def fetch(self) -> list[RawMeeting]:
            ...

        def normalize(self, raw: RawMeeting) -> CanonicalMeetingCandidate:
            ...

Create `app/normalize/canonical.py` with Pydantic models for `CanonicalMeetingCandidate`, `MeetingOccurrence`, and `CanonicalMeeting`. A meeting may have multiple occurrences if it meets on multiple days or times. Store recurring weekly meetings as explicit occurrences with `day_of_week`, `start_time_local`, `end_time_local`, and `timezone`.

Create database migrations for these tables:

    sources
    import_runs
    raw_meetings
    canonical_meetings
    meeting_occurrences
    review_flags
    snapshots

The `sources` table must have a unique key on normalized source URL and fellowship. The `raw_meetings` table must store a content hash so unchanged records can be skipped. The `canonical_meetings` table must store `status`, `first_seen_at`, `last_seen_at`, `last_verified_at`, and `confidence_score`.

Implement `MeetingGuideAdapter` in `app/adapters/meeting_guide.py`. It should request a configured JSON feed URL with `httpx`, parse the JSON array, validate basic fields, preserve the raw record, and normalize Meeting Guide fields into the canonical candidate model.

Implement `BmltAdapter` in `app/adapters/bmlt.py`. It should support root server URLs and request meeting search results in JSON. It must map BMLT fields into the canonical model and preserve source IDs.

Implement `AaWorldServicesDiscovery` in `app/sources/aa_world_services.py`. It should crawl the official AA World Services "Find A.A. Near You (World)" page and extract local A.A. resources into the source registry. It should support United States and Canada state or province listings, international country listings, and any local website, phone, or contact links exposed by those listing pages. It should not create canonical meeting records directly unless a linked local page clearly contains meeting data and is handled by a normal adapter.

Implement `CaWorldServicesDiscovery` in `app/sources/ca_world_services.py`. It should crawl known CA World Services meeting pages and extract local source links into the source registry. It should not create canonical meeting records directly unless the page clearly contains meeting data.

Implement `NaWorldServicesDiscovery` in `app/sources/na_world_services.py`. It should discover local NA source links from the NA in-person locator. It should support seed inputs for countries, major cities, or coordinates. The first implementation may store discovered local sites and phonelines without ingesting meetings.

Implement `SiteClassifier` in `app/sources/registry.py`. It should fetch a local source URL and classify it as `meeting_guide`, `bmlt`, `static_html`, `form_http`, `pdf`, `playwright_browser`, `manual_review`, or `unknown`. Classification should be conservative. If more than one type is detected, prefer structured APIs over HTML and HTML over browser automation.

Implement `StaticHtmlAdapter` after the classifier. It should only support sources whose selectors are configured in the source registry. Do not create a single generic parser that guesses arbitrary layouts. For each configured source, store CSS selectors for row, name, day, time, address, type, and notes.

Implement `FormHttpAdapter`. It should submit configured HTTP requests for local search forms. It must support GET and POST forms, query parameter templates, and paginated results if the source registry has the required configuration.

Implement `PlaywrightBrowserAdapter` last. It must run with strict timeouts and per-domain rate limits. It should be used only for sources marked `requires_browser = true`.

Implement `review/flags.py`. It should create flags for suspicious changes and sensitive data. Use regular expressions to detect personal emails, phone numbers in notes, Zoom passcodes, and likely personal names where possible. Detection does not need to be perfect; it should err toward human review.

Implement `export/snapshot.py`. It should write a JSON file named with a timestamp, for example `snapshots/meetings-2026-04-30T210000Z.json`. The snapshot should include source attribution and `last_verified_at`, but not raw payloads.

## Validation and Acceptance

The first milestone is accepted when the project can be installed, linted, and tested:

    cd ~/repos/recovery-meeting-ingestion
    python -m venv .venv
    . .venv/bin/activate
    pip install -e ".[dev]"
    ruff check .
    pytest

Expected result:

    ruff check .
    All checks passed!

    pytest
    tests pass with no network access required

The schema milestone is accepted when tests can construct valid canonical meetings, reject invalid records, and serialize a safe snapshot without raw payloads.

The AA discovery milestone is accepted when a saved HTML fixture from the AA World Services "Find A.A. Near You (World)" page produces source registry candidates rather than canonical meetings. The test should prove that United States or Canada location listings and international country listings are discovered and stored with fellowship `aa`.

The AA adapter milestone is accepted when a fixture containing Meeting Guide-style JSON imports into canonical candidates. The test must include at least one physical meeting and one online or hybrid meeting. The test must prove that `slug` becomes the stable source key and that day and time are normalized into meeting occurrences.

The CA discovery milestone is accepted when a saved HTML fixture from CA World Services produces source registry candidates rather than canonical meetings. The test should prove that country or area links are discovered and stored with fellowship `ca`.

The NA discovery milestone is accepted when a saved HTML or JSON fixture from the NA locator produces local source registry candidates rather than canonical meetings. The test should prove that local websites and phonelines are captured when available.

The BMLT adapter milestone is accepted when a fixture shaped like BMLT JSON imports into canonical candidates with stable source IDs, day/time data, and location fields.

The review milestone is accepted when tests show that suspicious records produce review flags. Test cases must include a meeting that loses its address, a source that drops more than 20 percent of its records, a record with possible personal contact information, and a record with missing timezone.

The snapshot milestone is accepted when running:

    python -m app.cli export-snapshot --dry-run

prints a summary similar to:

    Snapshot dry run
    active_meetings: 125
    stale_meetings: 7
    blocked_by_review: 14
    output: not written because --dry-run was set

The full MVP is accepted when an operator can run:

    python -m app.cli discover-sources --fellowship aa --dry-run
    python -m app.cli discover-sources --fellowship ca --dry-run
    python -m app.cli discover-sources --fellowship na --dry-run
    python -m app.cli ingest-source --source-id example-aa-feed --dry-run
    python -m app.cli report
    python -m app.cli export-snapshot --dry-run

and see deterministic output using fixtures or configured development sources.

## Idempotence and Recovery

All ingestion commands must be safe to rerun. A repeated import of unchanged data should update the import run history but should not create duplicate canonical meetings.

Do not hard-delete meetings when they disappear from a source. Mark them stale after the first missing run and inactive after repeated missing runs. The initial threshold should be three consecutive missing runs.

Every adapter should store raw payload hashes. If a parser changes and produces bad output, the operator should be able to rerun normalization against raw imports without refetching the remote site.

Database migrations must be additive during the MVP. Avoid destructive migrations until the project has backups and production data.

Browser automation must have timeouts. A single broken local site must not block the whole ingestion run.

If geocoding fails, keep the meeting as ungeocoded and create a review flag. Do not drop the meeting solely because geocoding failed.

## Artifacts and Notes

Important public source assumptions embedded in this plan:

    AA:
      Use AA World Services "Find A.A. Near You (World)" for local source discovery.
      Use Meeting Guide-compatible feeds based on the Code4Recovery specification.
      The spec is a format, not one global feed.

    CA:
      Use CA World Services meeting page `https://ca.org/meetings/` for local source discovery.
      Local CA websites are the likely source of actual meeting records.

    NA:
      Use NA World Services locator page `https://na.org/meetingsearch/find-na/` for local source discovery.
      NA World Services does not maintain a global in-person meeting database.
      Prefer BMLT where local NA sites expose it.

    SMART Recovery and LifeRing:
      Add after the AA, CA, and NA pipeline exists.
      Prefer official APIs or stable structured endpoints before HTML scraping.

Sensitive fields that must not be published by default:

    personal names
    personal email addresses
    personal phone numbers
    raw Zoom passcodes
    unreviewed private online meeting credentials
    raw copied page descriptions

Safe public fields:

    fellowship
    meeting name
    meeting type
    day and local time
    timezone
    public venue or approximate online origin
    city, region, country
    source URL
    source attribution
    last verified date
    meeting formats

## Interfaces and Dependencies

Use Python 3.12 or newer.

Use `httpx` for HTTP requests. Configure a timeout on every request. Use a default user agent from settings so site operators can identify the crawler.

Use `selectolax` for fast HTML parsing. Use `beautifulsoup4` only as a fallback for malformed pages if `selectolax` cannot parse a source reliably.

Use `pydantic` for request, source, raw, canonical, and snapshot models. Pydantic should validate data at adapter boundaries and before export.

Use `psycopg` for Postgres access. Do not introduce an ORM in the MVP. Keep SQL explicit and small.

Use `alembic` for migrations.

Use `tenacity` for retries with exponential backoff. Retries should apply only to transient network errors and rate-limit responses. Do not retry validation failures.

Use `structlog` for structured logs. Every import run should log `source_id`, `fellowship`, `adapter_type`, `records_fetched`, `records_changed`, `review_flags_created`, and `duration_ms`.

Use `rapidfuzz` for fuzzy deduplication candidates. Never auto-merge fuzzy matches without either high confidence or review.

Use `typer` for the CLI. Keep command names stable because scheduled jobs and operator documentation will depend on them.

Use `pytest` for tests. Network-dependent tests must be marked separately and should not run by default. Default tests must use fixtures.

Use `ruff` for formatting and linting. The project should configure ruff in `pyproject.toml`.

Use `playwright` only for the browser adapter. It should be an optional dependency so the core ingestion service can run without browser binaries when not needed.

Use `pypdf` only for the PDF adapter. PDF parsing should be optional and source-specific.

The canonical model should expose fields equivalent to:

    fellowship: aa | ca | na | lifering | smart
    source_id: string
    source_record_id: string
    source_url: string
    name: string
    meeting_type: in_person | online | hybrid | phone | unknown
    venue_name: optional string
    address_line1: optional string
    address_line2: optional string
    city: optional string
    region: optional string
    postal_code: optional string
    country: optional string
    latitude: optional decimal
    longitude: optional decimal
    is_approximate_location: boolean
    online_url: optional string
    phone_join_info: optional string
    formats: list of strings
    language: optional string
    accessibility_notes: optional string
    occurrences: list of weekly occurrence records
    first_seen_at: datetime
    last_seen_at: datetime
    last_verified_at: optional datetime
    status: active | stale | inactive | blocked_review
    confidence_score: decimal

The source registry model should expose fields equivalent to:

    id: string
    fellowship: aa | ca | na | lifering | smart
    name: string
    url: string
    country: optional string
    region: optional string
    adapter_type: meeting_guide | bmlt | static_html | form_http | pdf | playwright_browser | manual_review | unknown
    permission_status: allowed | needs_review | denied | unknown
    requires_browser: boolean
    rate_limit_seconds: integer
    last_success_at: optional datetime
    last_failure_at: optional datetime
    failure_count: integer
    config: JSON object

## Revision Notes

2026-04-30 / Codex: Created the initial self-contained ExecPlan for the SoberSpace global meeting ingestion service. The plan chooses a Python, Postgres, adapter-based architecture and records the source-specific strategy for AA, CA, and NA.

2026-04-30 / Codex: Executed the first implementation slice. Added the Python package skeleton, local database documentation, canonical/source/review/snapshot models, Alembic-wired initial schema, fixture-backed AA/CA/NA source discovery tests, Meeting Guide and BMLT adapter tests, and dry-run CLI commands.

2026-04-30 / Codex: Wired source discovery toward persistence. The discovery command can now read saved fixtures or fetch live world-service HTML, convert source candidates into stable source registry rows, and persist them through the Postgres repository when not running in dry-run mode.

2026-04-30 / Codex: Added the first structured ingestion command path. `ingest-source` can now run Meeting Guide or BMLT adapters from saved JSON fixtures, summarize fetched raw records, normalized candidates, and review flags, and persist raw meeting payloads when not in dry-run mode. Added an opt-in local Postgres source repository integration test guarded by `RUN_DB_TESTS=1`.

2026-04-30 / Codex: Verified the local Postgres path. Created `recovery_meeting_ingestion_dev`, applied Alembic migrations with `DATABASE_URL=postgresql:///recovery_meeting_ingestion_dev`, ran `RUN_DB_TESTS=1` repository integration tests, and confirmed repeated non-dry-run fixture ingestion records separate import runs while skipping unchanged raw payload inserts.

2026-04-30 / Codex: Added canonical persistence. Non-dry-run `ingest-source` now upserts normalized canonical meetings and replaces their weekly occurrence rows after raw payload persistence. Local Postgres integration tests cover source, import run, and canonical meeting repository behavior.

2026-04-30 / Codex: Added review and snapshot persistence. Ingestion now resolves prior open review flags for a source and inserts the current run's flags. Snapshot export now reads active canonical meetings and occurrences from Postgres, excluding meetings with open error-level review flags. Verified local dry-run and file export paths against `recovery_meeting_ingestion_dev`.

2026-04-30 / Codex: Hardened structured adapter fetching. Meeting Guide and BMLT adapters now use a shared HTTP JSON-array fetch helper with transient retry behavior, explicit fetch/payload exceptions, injectable `httpx` transports for tests, Meeting Guide response-shape tests, and a BMLT configured-endpoint test.

2026-04-30 / Codex: Implemented fallback adapter foundations. Static HTML and form-backed HTTP adapters now parse only configured selectors, PDF extraction is optional and review-gated, Playwright browser automation is optional and uses configured selectors after rendering, and static HTML fixtures can flow through the same ingestion service path.

2026-04-30 / Codex: Completed the remaining MVP execution-plan items. Added stale/inactive missing-run tracking, source-drop review flags, duplicate candidate detection, snapshot DB records and `latest.json` publication, registry-backed `ingest-all`, opt-in live smoke tests, and production handoff documentation for EC2 and SoberSpace.

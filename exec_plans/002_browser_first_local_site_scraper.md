# Refactor to a Browser-First Local Site Scraper

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan supersedes the feed-first parts of `exec_plans/001_global_meeting_ingestion.md`. The durable ingestion pieces from the original plan remain useful, but the default behavior must change from structured-feed detection to browser-first scraping of local service-body websites.

## Purpose / Big Picture

The app should discover local AA, CA, and NA service-body websites from world-service pages, then scrape meeting information from those local sites even when the sites require JavaScript, search forms, filters, pagination, accordions, maps, or other browser interaction.

After this refactor, an operator should be able to run a command that:

1. Discovers local sources from AA, CA, and NA world-service pages.
2. Visits each local source with Playwright.
3. Finds likely meeting pages inside that local site.
4. Interacts with common search and filter controls.
5. Captures rendered HTML.
6. Extracts meeting-looking records with Beautiful Soup.
7. Normalizes extracted records into the existing canonical meeting model.
8. Stores raw records, canonical candidates, review flags, and debug evidence.
9. Exports a reviewed snapshot for SoberSpace.

The goal is not perfect autonomous global scraping on the first pass. The goal is a browser-first scraping pipeline that can make useful progress across many local sites, expose exactly what it did, and send low-confidence or ambiguous results to review instead of silently publishing bad data.

## Progress

- [x] (2026-05-01) Added this ExecPlan for the browser-first local-site scraper refactor.
- [x] (2026-05-01T08:24Z) Added `app/scraping/` primitives: scrape result models, evidence writer/reader, meeting page scoring, confidence scoring, heuristic Beautiful Soup extraction, and raw-record conversion from extracted meetings.
- [x] (2026-05-01T08:24Z) Wired rendered HTML from `PlaywrightBrowserAdapter` through the new extractor so browser sources can produce records from configured selectors or heuristic tables/cards without requiring a selector map for every source.
- [x] (2026-05-01T08:24Z) Added confidence-aware ingest handling: low-confidence scraped records create review flags, and very-low-confidence scraped records remain raw/evidence data without becoming canonical candidates.
- [x] (2026-05-01T08:24Z) Added unit tests for meeting page scoring, configured extraction, table extraction, card extraction, confidence thresholds, evidence writing, and Playwright fixture ingestion without configured selectors.
- [x] (2026-05-01T08:42Z) Replaced the documented default feed-first workflow with browser-first `scrape-all`; kept `classify-sources` only as a legacy inspection command.
- [x] (2026-05-01T08:42Z) Added `app/scraping/browser_crawler.py` with Playwright lifecycle, same-site queue, max page/depth limits, candidate link prioritization, rendered HTML capture, optional screenshots, page scores, and crawl evidence.
- [x] (2026-05-01T08:42Z) Added `app/scraping/interactions.py` with configured action execution, action traces, common meeting/list/load-more/accordion clicks, and simple source-context search-form submission.
- [x] (2026-05-01T08:42Z) Completed the Beautiful Soup extraction slice for configured selectors, tables, repeated card/list containers, text fallback, source page metadata, and confidence metadata.
- [x] (2026-05-01T08:42Z) Completed confidence scoring and evidence integration for raw payload metadata, low-confidence review flags, very-low-confidence canonical suppression, summary JSON, rendered HTML, action/extraction traces, and screenshots when Playwright can capture them.
- [x] (2026-05-01T08:42Z) Added `scrape-source`, `scrape-all`, and `debug-scrape-source`; retained `ingest-source` and `ingest-all` with transition deprecation output.
- [x] (2026-05-01T08:42Z) Updated README and operations/source/data-policy docs for the browser-first workflow, and added CLI, crawler, extraction, and opt-in browser fixture tests.
- [x] (2026-05-01) Added live-tested BMLT hint fallback from rendered local-site HTML, so Crouton/BMLT-backed NA sites can be scraped through the browser-first service and then fetched via the discovered BMLT endpoint.
- [x] (2026-05-01) Hardened heuristic interactions after live CA tests: ordinary links are no longer clicked as buttons, generic WordPress/global search forms are no longer submitted with country names, non-HTML file links such as PDFs are skipped, and `networkidle` navigation timeouts fall back to `domcontentloaded`.
- [x] (2026-05-01) Expanded CA discovery to recursively follow `ca.org/meetings/...` listing pages, preserve country/region metadata from nested listing paths, and register external local sites while filtering known noise hosts.
- [x] (2026-05-01) Expanded AA discovery to read world-service filter options and fetch result pages for state/country filters instead of relying only on a small hard-coded list.
- [x] (2026-05-01) Expanded rendered HTML extraction for live CA formats: tables where the time cell includes the day, WordPress day-section paragraph lists, and GoDaddy Website Builder content blocks.
- [x] (2026-05-01) Added cross-page raw-record dedupe so duplicated local pages do not double-publish the same meeting.
- [x] (2026-05-01) Ran a controlled AA/CA/NA smoke batch: 24 sampled local sources, 65 pages visited, 23 successful crawls, 15 sources with candidates, 1,232 candidates, and 613 review flags. Report: `scrape_artifacts/smoke-20260501T103039Z/controlled_smoke_report.json`.
- [x] (2026-05-01) Added source-region/timezone inference for discovered AA/CA/NA labels so state/province listings such as Alabama, Arizona, Arkansas, and California carry better default timezone metadata into normalization.
- [x] (2026-05-01) Improved BMLT/Crouton handling by honoring rendered `custom_query` and recursive service-body configuration, and by extracting rendered BMLT table rows directly from browser artifacts.
- [x] (2026-05-01) Ran a second controlled AA/CA/NA smoke batch after the BMLT/timezone fixes: 24 sampled local sources, 65 pages visited, 23 successful crawls, 17 sources with candidates, 2,936 candidates, and 64 review flags. Report: `scrape_artifacts/smoke-20260501T111620Z/controlled_smoke_report.json`.

## Surprises & Discoveries

- Observation: The existing repo already has useful lower-level infrastructure.
  Evidence: `Source`, `RawMeeting`, canonical models, review flags, storage repositories, import runs, and snapshot export do not depend on Meeting Guide or BMLT specifically.

- Observation: The existing repo is currently feed-first.
  Evidence: `SourceProbeClassifier` probes for Meeting Guide and BMLT feeds, and marks arbitrary HTML/forms for manual review unless source-specific config exists.

- Observation: A fully generic scraper will need review and debug evidence from day one.
  Evidence: Local recovery sites vary widely and may expose incomplete results until search terms, region filters, map/list toggles, or pagination controls are used.

- Observation: The project test environment uses `.venv/bin/pytest`, not a globally installed `pytest`.
  Evidence: `pytest tests/test_optional_adapters.py tests/test_static_html_adapter.py` returned `/usr/bin/bash: line 1: pytest: command not found`; `.venv/bin/pytest ...` passed.

- Observation: The existing normalization path can be reused for heuristic browser records if the raw payload preserves familiar field names such as `name`, `day`, `time`, and `address_line1`.
  Evidence: `tests/test_optional_adapters.py::test_playwright_adapter_extracts_rendered_table_without_selectors` ingests a table fixture through `PlaywrightBrowserAdapter`, normalizes `Monday Main`, and preserves the configured `Europe/Dublin` timezone.

- Observation: The full browser-backed tests should remain opt-in in this repository.
  Evidence: `tests/test_browser_scraper.py` is skipped unless `RUN_BROWSER_TESTS=1` because it requires Playwright Chromium, while the default suite still validates crawler prioritization, extraction, CLI fixture scraping, and artifact writing without a browser runtime.

- Observation: The artifact-file fallback is sufficient for this refactor slice and avoids a migration.
  Evidence: `write_scrape_evidence` writes `summary.json`, rendered page HTML, and page JSON with actions and extracted payloads under `scrape_artifacts/`; persistence still uses existing raw/canonical/review/import-run tables.

- Observation: CA world-service discovery must follow the `ca.org/meetings/...` listing tree before scraping.
  Evidence: Live CA checks showed that scraping `ca.org/meetings/ca-online/` or country/listing pages directly produces world-service navigation and event/listing noise. After recursive listing discovery, `max_locations=4` found 55 external local CA sources including U.S. area sites, while `scrape-all` skips `WORLD_SERVICE_LISTING` rows.

- Observation: AA world-service discovery is filter-driven, not link-tree driven.
  Evidence: The live AA world page exposes 176 `state` and `cc` filter values. Discovery now reads those filter options and fetches each result page; a live `max_locations=3` sample returned 1,023 unique AA candidates from the base page plus the first three filter pages.

- Observation: The NA world search form does not need browser text entry for the current site.
  Evidence: `app/sources/na_world_services.py` uses NA's meeting locator AJAX endpoint at `https://na.org/wp-content/plugins/meetings-finder/ajax.php`; the browser form would only be needed if that backend endpoint changes.

- Observation: Several NA local sites embed BMLT configuration inside rendered Crouton pages.
  Evidence: Live browser scrapes against NYC NA and Kings Bay found BMLT hints in the rendered HTML and the fallback returned 177 and 140 candidate records respectively.

- Observation: CA local sites require multiple generic extraction patterns, not a single table parser.
  Evidence: Live CA samples included rendered meeting tables with `3:00 PM Friday` in the time column, WordPress pages with day headings followed by paragraph triplets, and GoDaddy Website Builder content blocks with `h4` names plus list-item times.

- Observation: Browser heuristics must be conservative around search and links.
  Evidence: Earlier live CA runs submitted `United States` into WordPress search forms and navigated into Google consent/search-result pages, and clicked ordinary theme/vendor links. The current interaction rules no longer do those things.

- Observation: Some discovered local pages are valid service sites but do not expose extractable meeting data in the first few pages.
  Evidence: Cyber Serenity crawled successfully but the reached pages had no meeting rows/cards/day sections. The pipeline records zero-result evidence rather than failing.

- Observation: Controlled smoke coverage is useful but still uneven by fellowship.
  Evidence: The 2026-05-01 controlled smoke batch found candidates for 4/8 AA sources, 7/8 CA sources, and 4/8 NA sources. NA produced the highest candidate count because several pages fell back to large BMLT feeds, but also the most review noise and duplicate regional overlap.

- Observation: BMLT-backed NA results need source-level dedupe and/or service-body filtering before scaling.
  Evidence: New York City Area and Manhattan Area each returned 177 candidates from the same broader BMLT-backed dataset, while Queens returned 615 candidates and 356 review flags.

- Observation: Rendered Crouton/BMLT table pages can be visible in browser artifacts even when extraction/fallback does not capture them.
  Evidence: Heart of New York Area rendered hundreds of meeting table rows in `scrape_artifacts/smoke-20260501T103039Z/na-fae97e8f1181/pages/001-fe64567794.html`, but produced zero candidates because the current table extractor does not understand that table structure and the BMLT hint parser did not derive a fetchable endpoint there.

- Observation: Timezone inference from discovery metadata is still incomplete.
  Evidence: Several CA smoke candidates normalized with `America/New_York` or `UTC` despite their local labels indicating Alabama, Arizona, California, or online/global coverage.

- Observation: Label-derived timezone inference reduced review noise for state-level CA sources, but cannot solve unlabeled local-area pages by itself.
  Evidence: The second controlled smoke run inferred `America/Phoenix` for Arizona, `America/Chicago` for Arkansas, and `America/Los_Angeles` for California sources, while CA Online and Antelope Valley still emitted 33 total `missing_timezone` flags because their discovered metadata is global or locally named without a known state mapping.

- Observation: Heart of New York NA required both recursive BMLT endpoint parsing and rendered table extraction.
  Evidence: The Crouton page exposes `services[]=1052` with recursive service-body behavior; the second controlled smoke run extracted 133 Heart of New York candidates where the first run extracted zero.

- Observation: NA extraction quantity is now high enough that precision and source scoping are the next bottlenecks.
  Evidence: The second controlled smoke run produced 2,681 NA candidates from 8 sampled NA sources, including 393 for New York City, 676 for Manhattan, 719 for Greater New York, and 614 for Queens. Those counts indicate overlapping regional datasets that should be deduped or scoped before unattended publication.

## Decision Log

- Decision: Make browser-first scraping the default local-source ingestion path.
  Rationale: The desired behavior is to scrape local sites directly, including sites that need JavaScript interaction, rather than avoiding them unless they expose a known structured feed.
  Date/Author: 2026-05-01 / Codex

- Decision: Keep the existing canonical, storage, review, and snapshot layers.
  Rationale: Those layers are still aligned with the product goal: preserve source evidence, normalize meeting data, flag risky records, and export a safe snapshot.
  Date/Author: 2026-05-01 / Codex

- Decision: Demote Meeting Guide and BMLT adapters to optional fallbacks or remove them from the default path.
  Rationale: The requested product behavior is local-site scraping, not structured feed discovery. Known feeds can still be useful as optimization or source-specific overrides, but they should not shape the main pipeline.
  Date/Author: 2026-05-01 / Codex

- Decision: Use Beautiful Soup for extraction from rendered HTML.
  Rationale: The browser crawler should produce HTML snapshots, and Beautiful Soup is a straightforward parser for heuristic extraction, CSS selectors, and debug-friendly traversal.
  Date/Author: 2026-05-01 / Codex

- Decision: Treat scraper output as probabilistic and reviewable.
  Rationale: Heuristic local-site scraping will generate uncertain results. Confidence scoring, evidence capture, and review flags are mandatory guardrails.
  Date/Author: 2026-05-01 / Codex

- Decision: Keep the first scraper primitives independent from the full browser crawler.
  Rationale: Page scoring, extraction, evidence writing, and confidence review can be validated with deterministic HTML fixtures before adding Playwright queueing and screenshots. This keeps the existing ingest path green while the crawler is still incomplete.
  Date/Author: 2026-05-01 / Codex

- Decision: Use the existing canonical normalizer for extracted browser records by converting `ExtractedMeeting` values into `RawMeeting` payloads with an `extraction` metadata object.
  Rationale: This preserves the current persistence and review flow while adding traceable scraper metadata, and avoids introducing a second canonical mapping layer.
  Date/Author: 2026-05-01 / Codex

- Decision: Do not add `scrape_runs` and `scrape_pages` database tables in this pass.
  Rationale: The ExecPlan allowed artifact files as the first implementation fallback. Avoiding a migration keeps the refactor focused on browser-first behavior while preserving existing durable raw/canonical/review/import-run storage.
  Date/Author: 2026-05-01 / Codex

- Decision: Keep `classify-sources`, Meeting Guide, and BMLT code as legacy/optional paths rather than deleting them immediately.
  Rationale: Existing tests and source-specific overrides still use them, but the README, source registry docs, and operations docs no longer present feed probing as the default workflow.
  Date/Author: 2026-05-01 / Codex

## Outcomes & Retrospective

2026-05-01T08:24Z: Milestones 1, 2, and the first parts of Milestones 5 and 6 are implemented. The repository now has tested scraper models, evidence files, page scoring, confidence scoring, and Beautiful Soup extraction for configured selectors, tables, repeated cards/lists, and text fallback. The Playwright adapter can ingest rendered HTML without configured selectors when the page has recognizable meeting tables or cards. The main remaining risk is still the browser crawler itself: it does not yet crawl same-site links, prioritize candidate pages, run heuristic interactions, or save screenshots/action traces from live Playwright pages.

2026-05-01T08:42Z: The browser-first refactor described in this ExecPlan is implemented. Operators now have `scrape-source`, `scrape-all`, and `debug-scrape-source` commands; the crawler can visit local sites with Playwright, stay on the same site, prioritize meeting links, run configured and heuristic interactions, capture rendered HTML, extract meeting-like records, add confidence metadata, create review flags for low-confidence records, suppress very-low-confidence canonical candidates, write debug artifacts, persist via the existing ingestion repositories, and export snapshots from canonical candidates. The main remaining operational risk is real-world scraper quality across highly varied local sites; that is mitigated by bounded crawling, evidence artifacts, and review flags rather than claiming perfect autonomous scraping.

2026-05-01: Live CA/NA trial results show the pipeline can now extract and normalize meeting data from several real local-site patterns. CA Online produced 25 online candidates, Alabama produced 7 deduped candidates from duplicated GoDaddy pages, Arizona produced 64 candidates, Arkansas produced 7 candidates from day pages, Northern California produced 25 candidates from a rendered app/table, and BMLT-backed NA local sites produced 177 and 140 candidates through the rendered-HTML fallback. Remaining limitations are site coverage and precision: some sites still need source-specific handling or deeper interaction, online meeting pages without URLs may normalize with phone/platform connection text, and review flags remain necessary for personal-contact or ambiguous records.

2026-05-01 controlled smoke batch: The scraper is ready for iterative coverage work, not unattended global publication. A 24-source sample produced 1,232 candidates from 15 sources, with 1 hard failure and 9 zero-result successful crawls. CA is the strongest current path in the sample. AA has useful generic coverage but still misses some table/list formats. NA needs BMLT/Crouton-specific handling, source filtering, and duplicate suppression before large runs because BMLT fallbacks can return broad regional datasets rather than the exact local service-body subset.

2026-05-01 second controlled smoke batch: The targeted fixes materially improved output quality. The same 24-source sample produced 2,936 candidates from 17 sources, with 1 hard failure and 6 zero-result successful crawls. Review flags dropped from 613 to 64 because source timezone inference resolved many missing-timezone cases, and Heart of New York NA now extracts 133 rendered BMLT/Crouton rows. Remaining work is narrower and operational: investigate zero-result AA/CA/NA sites, add source scoping/dedupe for overlapping NA regional BMLT results, and add more timezone mappings for local-area CA labels that do not expose a state in discovery metadata.

## Context and Orientation

The current repository has these useful areas:

    app/sources/
      aa_world_services.py
      ca_world_services.py
      na_world_services.py
      registry.py
      site_classification.py
    app/adapters/
      base.py
      static_html.py
      form_http.py
      playwright_browser.py
      meeting_guide.py
      bmlt.py
    app/normalize/
    app/storage/
    app/review/
    app/export/
    app/cli.py
    app/ingest.py

The source discovery modules should mostly stay. They answer the first question: "Which local service-body sites exist?" The storage, normalization, review, and export modules should also stay. The main refactor should happen around classification, ingest orchestration, and scraping adapters.

The current `classify-sources` command and `SourceProbeClassifier` are misaligned with the new goal. They try to find safe structured feeds before ingesting. The new goal is to open local sites with a browser and attempt scraping, while collecting enough evidence to make review practical.

## Target Architecture

The new default flow should be:

    world-service discovery
      -> local source registry
      -> browser scrape queue
      -> Playwright local-site crawler
      -> candidate meeting page detector
      -> interaction engine
      -> rendered HTML capture
      -> Beautiful Soup extraction
      -> confidence scoring
      -> RawMeeting records
      -> canonical normalization
      -> review flags
      -> persistence and snapshot export

New package layout:

    app/scraping/
      __init__.py
      browser_crawler.py
      interactions.py
      meeting_page_detector.py
      extract_meetings.py
      scoring.py
      evidence.py
      models.py
      raw_records.py
      service.py

Existing feed adapters remain temporarily for legacy tests and source-specific overrides, but they are not part of the documented default workflow. After the browser-first path has real-world operating history, remove or archive feed-first code that no longer serves the product.

## Data Model Changes

Keep the existing `sources`, `raw_meetings`, `canonical_meetings`, `meeting_occurrences`, `review_flags`, `import_runs`, and `snapshots` tables if possible.

Add fields or tables only where needed:

    scrape_runs
      id
      source_id
      started_at
      finished_at
      status
      pages_visited
      pages_extracted
      records_extracted
      error_message

    scrape_pages
      id
      scrape_run_id
      source_id
      url
      final_url
      title
      html_hash
      screenshot_path
      evidence_path
      page_score
      extracted_count

If a schema migration feels too heavy for the first slice, write evidence to JSON files under `scrape_artifacts/` and store only summary metadata in the import run. The durable table can come after the crawler is proven.

Each raw meeting payload should include extraction metadata:

    {
      "name": "...",
      "day": "...",
      "time": "...",
      "address_line1": "...",
      "city": "...",
      "online_url": "...",
      "formats": "...",
      "extraction": {
        "method": "heuristic_table_row",
        "confidence": 0.82,
        "source_page_url": "https://...",
        "signals": ["day", "time", "address", "repeated_container"],
        "selector_hint": "table.meetings tr"
      }
    }

## Scraper Behavior

The browser crawler should:

1. Open the source URL with Playwright.
2. Stay on the same registrable domain unless a link is clearly a local meeting finder owned by the service body.
3. Crawl a bounded number of pages per source.
4. Prioritize links whose URL or text includes meeting-related terms.
5. Avoid social media, donation pages, login pages, unrelated news/blog content, and external sites unless explicitly allowed.
6. Capture final rendered HTML for each candidate page.
7. Record actions and page scores.

Suggested crawler limits for the first implementation:

    max_pages_per_source = 20
    max_depth = 2
    page_timeout_ms = 20000
    action_timeout_ms = 5000
    max_actions_per_page = 20

Meeting page signals:

    URL contains:
      meeting
      meetings
      find-a-meeting
      find-meeting
      schedule
      where-to-find
      locator

    Text contains:
      meeting list
      find a meeting
      meeting finder
      search meetings
      in-person
      online meetings
      today
      monday
      tuesday
      wednesday
      thursday
      friday
      saturday
      sunday

    HTML contains:
      repeated day/time/address blocks
      table headers for day/time/location
      form fields for city/postcode/day/distance
      map/list toggle controls

## Interaction Engine

The interaction engine should try low-risk actions that reveal meeting results:

1. Click obvious meeting-related tabs or buttons.
2. Click list view controls when a map/list toggle exists.
3. Expand accordions that contain meeting-related text.
4. Click load-more or next-page buttons until a bounded limit is reached.
5. Fill search fields using source context when available.
6. Select broad filters such as "All", "Any", or default country/region values.
7. Submit forms and wait for meeting-looking results.

Common form field mappings:

    city:
      source.city
      source.region
      source.country

    postcode / zip:
      optional configured seed values only

    day:
      All
      Any
      blank default first

    distance / radius:
      largest available reasonable value

    meeting type:
      All
      In person
      Online

The first version should not invent precise locations. If a form requires a postcode or exact address and none is configured, record a `needs_search_seed` review/evidence reason and move on.

Supported action primitives:

    fill
    click
    select_option
    press
    check
    uncheck
    wait_for_selector
    wait_for_load_state
    wait_for_timeout

Configured per-source browser actions should still be supported and should run before heuristic actions.

## Extraction Engine

The extraction engine should parse rendered HTML with Beautiful Soup and emit meeting payloads.

Extraction strategies, in order:

1. Configured CSS selectors.
2. Tables with day/time/location/name-like headers.
3. Repeated cards or list items containing day and time.
4. Text blocks with schedule-like patterns.
5. Online meeting link blocks.

Table extraction:

    Identify tables where headers or nearby text include at least two of:
      day
      time
      meeting
      location
      address
      city
      group
      type
      format

    Map columns into canonical-ish payload fields:
      name
      day
      time
      venue_name
      address_line1
      city
      formats
      notes
      online_url

Card/list extraction:

    Find repeated sibling elements that each contain:
      at least one day signal
      at least one time signal
      and one of address, venue, online link, or meeting name

    Score repeated containers higher when several siblings share the same class names or structure.

Text extraction:

    Use this only as a fallback.
    Split into blocks.
    Detect day/time lines.
    Attach nearby venue/address/online URL lines.
    Mark confidence lower than table/card extraction.

Do not publish records from very low-confidence extraction without review.

## Confidence Scoring

Each extracted record should get a score from 0.0 to 1.0.

Positive signals:

    + day parsed
    + time parsed
    + meeting name found
    + address or online URL found
    + repeated row/card structure
    + source page URL is meeting-related
    + table headers match known fields
    + timezone inferred from source config or country

Negative signals:

    - no day
    - no time
    - no location or online info
    - extracted from generic page text
    - looks like event/news content
    - contains personal contact details
    - duplicate-like record within same source

Initial thresholds:

    confidence >= 0.75:
      eligible for canonical candidate with normal review rules

    0.45 <= confidence < 0.75:
      create canonical candidate but add review flag

    confidence < 0.45:
      store evidence, do not create canonical candidate by default

## CLI Refactor

Keep:

    discover-sources
    export-snapshot
    report

Add:

    scrape-source
    scrape-all
    debug-scrape-source

Change:

    ingest-source
      Either remove it or keep it as an alias for scrape-source during transition.

    ingest-all
      Either remove it or keep it as an alias for scrape-all during transition.

    classify-sources
      Remove from the default workflow. If kept, rename to inspect-sources or make it report scraper readiness only.

Target commands:

    python -m app.cli discover-sources --fellowship aa --no-dry-run
    python -m app.cli scrape-all --fellowship aa --no-dry-run
    python -m app.cli debug-scrape-source --source-id aa-example --output-dir scrape_artifacts/debug
    python -m app.cli export-snapshot --no-dry-run

`scrape-source` options:

    --source-id
    --dry-run / --no-dry-run
    --max-pages
    --max-depth
    --save-artifacts / --no-save-artifacts
    --headful

`scrape-all` options:

    --fellowship
    --limit
    --dry-run / --no-dry-run
    --max-pages-per-source
    --only-unknown
    --include-failed

`debug-scrape-source` should always save:

    visited URL list
    final rendered HTML for candidate pages
    screenshots
    action trace
    extraction trace
    raw extracted payloads

## Code Removal / De-Emphasis

The following code should be removed from the default path:

    app/sources/site_classification.py
    Meeting Guide probing inside source classification
    BMLT probing inside source classification
    feed-first adapter selection in ingest orchestration

The following code may be kept temporarily:

    app/adapters/meeting_guide.py
    app/adapters/bmlt.py
    app/adapters/form_http.py
    app/adapters/static_html.py

Keep them only if they are useful as source-specific overrides or tests. If they create confusion or keep the CLI feed-first, remove them after the browser-first scraper is passing tests.

## Implementation Plan

### Milestone 1: Scraping Models and Evidence

Create `app/scraping/models.py` with:

    CrawlSettings
    ScrapedPage
    BrowserActionTrace
    ExtractedMeeting
    ScrapeSourceResult

Create `app/scraping/evidence.py` with helpers to write:

    rendered HTML
    screenshots
    action traces
    extraction traces
    summary JSON

Acceptance:

    Unit tests can create scrape results and write/read evidence files under tmp_path.

### Milestone 2: Meeting Page Detector

Create `app/scraping/meeting_page_detector.py`.

Implement scoring for URLs, link text, page titles, headings, forms, tables, and meeting-like text.

Acceptance:

    Fixture pages with obvious meeting links score high.
    Fixture pages for blog/news/donate/contact score low.

### Milestone 3: Browser Crawler

Create `app/scraping/browser_crawler.py`.

Implement:

    Playwright browser lifecycle
    same-site URL queue
    max page/depth limits
    candidate link prioritization
    rendered HTML capture
    optional screenshot capture

Acceptance:

    A local fixture site served by the test suite can be crawled.
    The crawler finds `/meetings` from a homepage.
    The crawler does not leave the allowed domain.

### Milestone 4: Interaction Engine

Create `app/scraping/interactions.py`.

Implement:

    configured action execution
    load-more clicks
    accordion expansion
    list-view toggle clicks
    simple search form submission
    action trace recording

Acceptance:

    Tests with mocked Playwright page objects verify action ordering.
    Browser-backed fixture test verifies that hidden meeting results become visible after interaction.

### Milestone 5: Beautiful Soup Extraction

Create `app/scraping/extract_meetings.py`.

Implement:

    configured selector extraction
    table extraction
    repeated card/list extraction
    low-confidence text-block extraction

Acceptance:

    Tests cover fixture table, card, list, online-only, and noisy pages.
    Extracted payloads contain source page URL and confidence metadata.

### Milestone 6: Scoring and Review Integration

Create `app/scraping/scoring.py`.

Wire confidence into raw payloads and review flags.

Acceptance:

    Low-confidence records create review flags.
    Very low-confidence records are saved as evidence but not normalized by default.

### Milestone 7: Ingest Orchestration Refactor

Refactor `app/ingest.py` so browser scraping can produce raw records directly from a `Source`.

Options:

    rename ingest_source -> scrape_source
    or keep ingest_source as a thin wrapper during transition

Default adapter selection should no longer prefer Meeting Guide or BMLT. It should call the browser-first scraper unless a source has explicit configured selectors or browser actions.

Acceptance:

    Existing persistence still stores raw records, canonical candidates, review flags, and import run status.

### Milestone 8: CLI Refactor

Update `app/cli.py`:

    add scrape-source
    add scrape-all
    add debug-scrape-source
    remove classify-sources from documented workflow
    optionally keep old ingest commands as aliases with deprecation text

Acceptance:

    Dry-run scrape-source prints pages visited, records extracted, candidates normalized, review flags, and artifact path.
    Non-dry-run scrape-source persists the same kinds of data as current ingest-source.

### Milestone 9: Documentation and Cleanup

Update:

    README.md
    docs/source_registry.md
    docs/data_policy.md
    docs/operations_ec2.md

Remove or archive stale feed-first docs.

Acceptance:

    Docs explain the new browser-first workflow.
    No docs present Meeting Guide or BMLT probing as the default path.

## Testing Strategy

Use test fixture sites instead of live sites for most tests.

Add fixtures:

    tests/fixtures/sites/simple_static/
    tests/fixtures/sites/search_form/
    tests/fixtures/sites/load_more/
    tests/fixtures/sites/accordion/
    tests/fixtures/sites/noisy_non_meeting/

Test layers:

    unit tests for URL/page scoring
    unit tests for extraction from saved HTML
    mocked Playwright tests for action primitives
    browser-backed integration tests for local fixture sites
    CLI dry-run tests
    repository tests remain opt-in for local Postgres

Browser-backed tests may be skipped unless Playwright and Chromium are installed:

    RUN_BROWSER_TESTS=1 pytest tests/test_browser_scraper.py

Full validation:

    .venv/bin/python -m ruff check app tests
    .venv/bin/python -m mypy app
    .venv/bin/python -m pytest

Current validation transcript from 2026-05-01T08:24Z:

    .venv/bin/ruff check app tests
    All checks passed!

    .venv/bin/mypy app
    Success: no issues found in 42 source files

    .venv/bin/pytest
    46 passed, 8 skipped in 0.94s

Current validation transcript from 2026-05-01T08:42Z:

    .venv/bin/ruff check app tests
    All checks passed!

    .venv/bin/mypy app
    Success: no issues found in 45 source files

    .venv/bin/pytest
    48 passed, 9 skipped in 0.97s

## Risks and Mitigations

Risk: False positives from arbitrary page text.
Mitigation: Confidence thresholds, review flags, and evidence capture.

Risk: Search forms require unknown local inputs.
Mitigation: Use source country/region/city only when available. Otherwise record `needs_search_seed`.

Risk: Browser crawling becomes slow or expensive.
Mitigation: Strict per-source page, depth, action, and timeout limits.

Risk: Local sites block automation.
Mitigation: Respect rate limits, use a clear user agent, store failure reasons, and keep manual review paths.

Risk: Existing feed tests and adapters slow down the refactor.
Mitigation: Move feed-first tests behind legacy modules or remove them when their behavior is no longer part of acceptance.

Risk: Debugging failures becomes impossible.
Mitigation: Save rendered HTML, screenshots, action traces, extraction traces, and summary JSON for debug runs.

## Validation and Acceptance

The refactor is accepted when:

1. `discover-sources` still discovers AA, CA, and NA local service-body sources.
2. `scrape-source` can scrape a local fixture site with static meeting HTML.
3. `scrape-source` can scrape a local fixture site that requires form interaction.
4. `scrape-source` can scrape a local fixture site that requires clicking load-more or expanding accordions.
5. Extracted meetings become `RawMeeting` records and canonical candidates.
6. Low-confidence results create review flags.
7. Debug artifacts show what pages were visited, what actions ran, and what was extracted.
8. `scrape-all --dry-run` can iterate source registry rows without invoking feed-first classification.
9. `export-snapshot` still works from canonical candidates.
10. Lint, type checks, and tests pass.

Expected final command flow:

    python -m app.cli discover-sources --fellowship aa --no-dry-run
    python -m app.cli scrape-all --fellowship aa --no-dry-run
    python -m app.cli export-snapshot --no-dry-run

Expected local checks:

    .venv/bin/python -m ruff check app tests
    .venv/bin/python -m mypy app
    .venv/bin/python -m pytest

Revision note, 2026-05-01T08:24Z: Updated this plan after implementing the first scraper primitives and Playwright rendered-HTML extraction bridge. The progress, discoveries, decisions, retrospective, and validation sections now reflect the current worktree so the next implementation step can start with the browser crawler and interaction engine.

Revision note, 2026-05-01T08:42Z: Updated this plan after completing the crawler, interaction engine, CLI refactor, docs cleanup, tests, and validation. The plan now records the artifact-file decision instead of database scrape-run tables and marks the browser-first refactor complete.

# NA Source Discovery, Classification, And Concurrent Scrape

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds. This file follows `PLANS.md` in this repository.

## Purpose / Big Picture

SoberSpace currently exports Narcotics Anonymous meetings, but the active NA meeting set is narrow: the latest checked snapshot contains 2,681 NA meetings, all from United States sources in the New York area. The source registry is much broader, with 929 NA sources across 124 countries, but most website sources are still not configured for automated scraping. After this work, NA should follow the same operational model as AA and CA: refresh source discovery when possible, classify local websites into scraper adapters, run controlled browser scrape batches, fix extractor gaps, then run the full scrape with bounded concurrency and export a reviewed snapshot.

The user-visible result is visible by running `snapshots/latest.json` through `jq` and seeing NA meeting counts and geographic coverage increase. The operational result is visible in the database: more NA sources should have `adapter_type='playwright_browser'` or a structured feed adapter, more NA sources should have active canonical meetings, and `review_flags` should have no open errors before publication.

## Progress

- [x] (2026-05-24T15:05+01:00) Confirmed baseline NA state: 929 sources, 837 local-service-body website sources, 92 phone/manual-review sources, 2,681 active NA meetings, and active meetings from only 6 source IDs.
- [x] (2026-05-24T15:06+01:00) Confirmed stored NA source registry spans 124 countries, 607 United States sources across 51 regions, and 38 Canada sources across 8 provinces.
- [x] (2026-05-24T15:07+01:00) Confirmed a live NA discovery dry-run currently fails at `https://na.org/wp-content/plugins/meetings-finder/ajax.php` with HTTP 403.
- [x] (2026-05-24T15:10+01:00) Created this ExecPlan and recorded the requirement that full NA scraping must use the existing bounded `scrape-all --concurrency` option.
- [x] (2026-05-24T15:55+01:00) Repaired live NA discovery refresh by fetching the locator page first and falling back to a same-origin Playwright `fetch` when Cloudflare blocks direct HTTP. A live `--max-locations 1` dry-run returned 25 candidates instead of failing with HTTP 403.
- [x] (2026-05-24T15:58+01:00) Updated source classification so generic meeting forms and meeting pages are classified as `playwright_browser` with `requires_browser=True` instead of `manual_review`; focused tests, ruff, and mypy passed.
- [x] (2026-05-24T16:25+01:00) Persisted the first 50-source NA classification batch. NA source counts changed to 795 unknown local-service-body sources, 39 `playwright_browser` local-service-body sources, 3 BMLT meeting-feed sources, and 92 phone/manual-review sources.
- [x] (2026-05-24T16:35+01:00) Ran a controlled concurrent NA scrape/import batch with `--limit 30 --concurrency 4` into `scrape_artifacts/na-controlled-20260524T152600Z`. The batch completed 30/30 sources, increased active NA meetings from 2,681 to 4,487 before cleanup, and exposed timezone, BMLT adapter preservation, and downloadable-link crawler gaps.
- [x] (2026-05-24T16:55+01:00) Patched NA/BMLT timezone inference, preserved structured feed adapters when browser scraping wraps a BMLT source, and skipped known calendar/list download URLs. Replayed safe artifacts and reran the two download-failed sources; active NA meetings reached 4,944 across 21 sources and 10 countries, with only two open NA `missing_timezone` warnings.
- [x] (2026-05-24T16:58+01:00) Exported a refreshed snapshot at `snapshots/meetings-2026-05-24T153419Z.json` with 103,863 active meetings and `blocked_by_review=0`.
- [x] (2026-05-24T17:00+01:00) Ran full validation: `.venv/bin/ruff check app tests`, `.venv/bin/mypy app`, and `.venv/bin/pytest -q` all passed. Full pytest reported 165 passed and 13 skipped.
- [x] (2026-05-24T17:25+01:00) Added `classify-sources --concurrency`, `--offset`, and default skipping for already-classified unknowns. Three concurrent classification chunks classified all remaining NA website sources or recorded a classification reason. Final NA source counts were 614 `playwright_browser`, 42 BMLT, 180 classified unknowns, 92 phone/manual-review, and 1 PDF/manual-review.
- [x] (2026-05-24T17:35+01:00) Started a full NA scrape/import using `--concurrency 8` and `--max-pages-per-source 12` into `scrape_artifacts/na-full-20260524T163000Z`. The original selector included 834 sources, including classified unknowns and direct feed sources wrapped as browser sources.
- [x] (2026-05-24T18:05+01:00) While the first full scrape continued, patched `scrape-all` so classified unknowns are skipped by default and direct BMLT/Meeting Guide sources use structured ingestion instead of browser crawling. Focused validation passed: `ruff app/cli.py tests/test_cli.py`, `mypy app/cli.py`, and `pytest tests/test_cli.py`.
- [x] (2026-05-24T18:40+01:00) Tightened remembered meeting-page refresh behavior. The crawler already seeded `successful_pages` and `last_successful_page_url` ahead of the homepage; it now skips failed remembered URLs without failing the source, skips link exploration from empty remembered pages, and stops on remembered pages only when the current record count is comparable to the previous successful count. Focused validation passed: `ruff app/scraping/browser_crawler.py tests/test_scraping_primitives.py`, `mypy app/scraping/browser_crawler.py`, and `pytest tests/test_scraping_primitives.py`.
- [x] (2026-05-24T19:14+01:00) Completed the first full concurrent NA scrape/import, audited review flags, resolved two audited New York/Manhattan source-drop blockers, and exported `snapshots/meetings-2026-05-24T181439Z.json` with `blocked_by_review=0`.
- [x] (2026-05-24T19:40+01:00) Added and ran concurrent `cleanup-timezones` for NA. It resolved 5,725 of 5,727 open NA `missing_timezone` warnings using deterministic source/country/region hints and exported `snapshots/meetings-2026-05-24T183959Z.json` with `blocked_by_review=0`.
- [x] (2026-05-24T20:25+01:00) Added `scrape-all --only-failed` and `--only-zero-records` retry filters, expanded NA common meeting path guesses, and ran a targeted concurrent retry over 352 failed or zero-record NA sources with `--concurrency 8`.
- [x] (2026-05-24T20:55+01:00) Fixed the two open retry errors: BMLT normalization now preserves non-URL virtual meeting text as `phone_join_info`, and remembered successful pages no longer submit seeded search forms before extraction. Reingested Greater Orlando and reran South King County, restoring 52 active rows there.
- [x] (2026-05-24T21:00+01:00) Re-ran concurrent timezone cleanup, added a deterministic Turkey timezone hint, exported `snapshots/meetings-2026-05-24T193936Z.json`, and completed full validation: ruff passed, mypy passed, and pytest reported 181 passed and 13 skipped.
- [x] (2026-05-24T21:10+01:00) Ran a concurrent audit of the remaining 33 failed and 274 zero-record NA browser sources. Failed sources are mostly transport failures; zero-record sources grouped into 82 possible missed structured feeds, 44 parser-gap candidates, 5 iframe/embed candidates, 17 PDF/printable candidates, 33 meeting-keyword-only pages, 90 blocked/captcha pages, and 3 low-signal pages.
- [x] (2026-05-24T21:35+01:00) Patched BMLT endpoint detection to decode base64 `data:text/javascript` Crouton scripts and numeric recursive/service-body config. A targeted concurrent retry recovered Pecos Valley, Colorado Region, and New Brunswick while rejecting zero-yield endpoints. Two area-level Colorado duplicate imports were marked stale because their pages embedded the same region-wide BMLT endpoint. Exported `snapshots/meetings-2026-05-24T203502Z.json` with `blocked_by_review=0`; full validation passed with 179 tests and 13 skipped.
- [x] (2026-05-24T21:50+01:00) Patched parser-gap extraction for classed `.meeting-row` schedules that inherit location context from a surrounding block. A two-source concurrent retry recovered Texarkana (23 rows) and Central Louisiana (25 rows), leaving NA at 63,864 active meetings across 567 active sources. Exported `snapshots/meetings-2026-05-24T204737Z.json` with `blocked_by_review=0`.
- [x] (2026-05-24T22:05+01:00) Patched additional parser gaps for heading/day-time tables, localized day-column matrix tables, and Slovenian location/time sections. Concurrent retry recovered StAr (45 rows), Aruba (5 rows), and Slovenia (8 rows). Added deterministic timezone hints for Stavropol Krai, Aruba, and Slovenia, resolved the 50 new timezone warnings, and exported `snapshots/meetings-2026-05-24T210155Z.json` with `blocked_by_review=0`.
- [x] (2026-05-24T22:40+01:00) Added a PDF text fallback using system `pdftotext`, conservative meeting-list PDF link filtering, and a PDF-specific plain-text extractor. A concurrent PDF retry recovered eight zero-record NA sources: Kern County (49), CAN Area (22), Central Vancouver Island (25), Greater Hattiesburg/DHOMA (10), Lewis & Clark/UMR (34), Southwest Missouri (41), Spring Area (27), and one 3-row list source. The first retry also re-imported a duplicate Colorado area BMLT feed; those 327 duplicate Serenity Unlimited rows were inactivated again. Exported `snapshots/meetings-2026-05-24T213631Z.json` with `blocked_by_review=0`, leaving NA at 64,133 active meetings across 578 active sources.
- [x] (2026-05-24T22:55+01:00) Added iframe/embed recovery for the New Zealand NA meeting picker JSON endpoint and public Google Calendar ICS embeds. A concurrent retry recovered New Zealand (215), CASNA/Harrisburg (50), Magic Valley (9), and Southern Idaho Region (65). The High Desert area calendar was inactivated as a duplicate of the broader Southern Idaho region calendar. Exported `snapshots/meetings-2026-05-24T215203Z.json` with `blocked_by_review=0`, leaving NA at 64,472 active meetings across 582 active sources.
- [x] (2026-05-24T23:20+01:00) Ran the blocked/dead-site and source-replacement bucket concurrently. HTTPS common-name errors are now retried with browser certificate errors ignored, and direct `?current-meeting-list` source URLs are fetched as downloadable PDFs before Playwright navigation. The pass recovered CAN Needles (22) plus nine direct current-meeting-list PDF sources: Central Detroit (33), Four Corners (20), Rochester (29), Southwest Arizona (19), Detroit East (31), Detroit West (46), Alabama/NW Florida Region (151), Southeast Texas (26), and Bosque/Greater Albuquerque (55). Exported `snapshots/meetings-2026-05-24T221606Z.json` with `blocked_by_review=0`, leaving NA at 64,904 active meetings across 592 active sources.
- [x] (2026-05-24T23:55+01:00) Added repeated `scrape-all --source-id` filtering so curated retry buckets can run concurrently without rerunning the whole failed/zero set. A broad 234-source concurrent bucket timed out after 78 sources but recovered 398 meetings and 21 active sources, including Quebec Region (338), Costa Rica (15), Kostroma (9), Bahamas (4), Tamilnadu (1), Moldova (1), and fourteen 2-row Mexico area sources. A second 50-source quick bucket with a lower page cap timed out after 29 sources and recovered 14 more Ukraine meetings from Lviv (6) and Poltava (8). Added timezone hints for Bahamas, Moldova, and recovered Mexico regions, exported `snapshots/meetings-2026-05-24T225347Z.json` with `blocked_by_review=0`, and left NA at 65,316 active meetings across 615 active sources.
- [x] (2026-05-24T23:13Z) Added Japanese meeting-list PDF link detection and a Japanese PDF text extractor with localized weekday and time-range normalization. A targeted concurrent Japan retry recovered Chubu (109 rows) with no review flags.
- [x] (2026-05-24T23:13Z) Prevented generic heuristic search-form submission when a loaded page already exposes deeper meeting-directory links. A targeted concurrent Ireland retry recovered four NA Ireland sources, each with 348 active rows and no review flags.
- [x] (2026-05-24T23:13Z) Re-ran timezone cleanup and exported `snapshots/meetings-2026-05-24T231347Z.json` with `blocked_by_review=0`. NA now has 66,817 active meetings across 620 active sources; the only open flags remain two Australia online-only `missing_timezone` warnings.
- [x] (2026-05-24T23:39Z) Added Japanese paragraph schedule extraction, prioritized `najapan.org` child schedule pages within the current area branch, and disabled remembered-page shortcuts for Japan area sources because remembered day pages are partial. A clean concurrent Japan source rerun recovered the Japan Region national PDF (463), Chubu PDF (109), and ten area branches: Kanto (69), Kyushu (47), Gunma (21), Chugoku (19), Hokkaido (38), Tohoku (79), Kansai (122), Kita Kanto (64), Shikoku (10), and South Kanto (120). Okinawa remains zero because the source page returns a server error. Exported `snapshots/meetings-2026-05-24T233903Z.json` with `blocked_by_review=0`; NA now has 67,869 active meetings across 631 active sources.
- [x] (2026-05-25T00:10Z) Added a reusable concurrent `audit-zero-sources` command and refined zero-source classification so generic `src=` markup no longer creates false embed/calendar candidates. A fresh NA audit wrote `scrape_artifacts/na-zero-audit-20260524T235748Z/`, reducing the broad embed bucket from 149 to 5 and generating a 60-source curated retry list.
- [x] (2026-05-25T00:10Z) Ran the curated 60-source retry concurrently with `--concurrency 8`. The retry recovered 872 rows before cleanup across 11 sources; one known Colorado region-wide duplicate import under Bringing Freedom East was inactivated (327 rows) and its 275 warnings were resolved. Net NA coverage is now 68,414 active meetings across 641 active sources. Exported `snapshots/meetings-2026-05-25T001044Z.json` with `blocked_by_review=0`.
- [x] (2026-05-25T00:26Z) Added broad-area result quarantine for NA area sources and fixed heuristic browser clicks so menu-toggle spans inside navigation anchors are not clicked. A 10-source concurrent CRNA retry recovered the Carolina Region full list (1,852 rows) plus eight local CRNA area pages: Lake Norman (13), Greater Pee Dee (30), Central Piedmont (28), Catawba Valley (27), GAP (30), Lowcountry (16), North Central Carolina (28), and Upper South Carolina (38). South Coastal also pulled the full regional list, so those 1,852 duplicate area rows were inactivated. Exported `snapshots/meetings-2026-05-25T002554Z.json` with `blocked_by_review=0`; NA now has 70,476 active meetings across 650 active sources.
- [x] (2026-05-25T00:45Z) Re-ran the zero-source audit concurrently after the CRNA fixes. The remaining zero-active browser set fell to 177 sources and the curated retry list fell to 39. Ran three concurrent focused buckets: 17 structured-feed candidates recovered Marietta (31), 9 PDF/printable candidates recovered Eastern Nebraska (59), and 11 parser/embed candidates recovered East End (1). Exported `snapshots/meetings-2026-05-25T004502Z.json` with `blocked_by_review=0`; NA now has 70,567 active meetings across 653 active sources. A final concurrent audit wrote `scrape_artifacts/na-zero-audit-20260525T004523Z/`, leaving 174 zero-active browser sources and 36 curated retry candidates.
- [x] (2026-05-25T00:55Z) Ran a concurrent dry-run diagnostic over all 36 remaining curated retry candidates into `scrape_artifacts/na-completion-diagnostic-20260525T004814Z`. No source produced importable records under the current generic scraper. South Coastal again extracted a 1,854-row regional-scale table and was correctly blocked by broad-area quarantine. The completion audit document `docs/na_completion_audit_2026-05-25.md` classifies the remaining 36 as 1 broad/duplicate risk and 35 source-specific/manual parser follow-ups.
- [x] (2026-05-25T01:35Z) Added source-specific direct recovery for the Litoral Norte Gaucho Google Site via filtered Brazil `cade-o-grupo` AJAX and for Red River via the current `www.redriverna.com` OklaTex meeting schedule PDF. Persisted the three resolved sources concurrently: Litoral (16 rows), Red River Oklahoma (6), and Red River Texas (29), all with zero review flags. Exported `snapshots/meetings-2026-05-25T013537Z.json` with `blocked_by_review=0`; NA now has 71,983 active meetings across 661 active sources.
- [x] (2026-05-25T01:48Z) Added source-specific direct BMLT mappings for eight remaining structured-feed candidates: Downtown Philly (17), Greater Albuquerque (45), Hawaii Region (147), Lone Star Region (623), Mendocino (42), Monterey (33), Ozark (60), and Tejas Bluebonnet (589). Persisted the eight-source batch concurrently with zero review flags and exported `snapshots/meetings-2026-05-25T014811Z.json` with `blocked_by_review=0`; NA now has 73,539 active meetings across 669 active sources.
- [x] (2026-05-25T09:13Z) Generalized linked `current-meeting-list` PDF recovery, including button `data-url` targets, and persisted three formerly zero-active NA sources: Just for Today Kansas (60), Southern Oregon (40), and Appalachian/CVAANA (22). All three had zero review flags. Exported `snapshots/meetings-2026-05-25T091323Z.json` with `blocked_by_review=0`; NA now has 73,661 active meetings across 672 active sources.
- [x] (2026-05-25T09:48Z) Fixed low-score rendered-page candidates so they no longer block linked PDF fallback. Persisted Palm Coast (81) and Rock River (46), both with zero review flags. Exported `snapshots/meetings-2026-05-25T094825Z.json` with `blocked_by_review=0`; NA now has 73,788 active meetings across 674 active sources.
- [x] (2026-05-25T10:05Z) Ran all 15 remaining audited NA candidates concurrently with `--concurrency 6`. No additional safe imports were found. River Coast and Bringing Freedom East now reach region-wide generated PDFs, so broad current-list PDF quarantine was added and verified; both dry-runs now return zero normalized candidates with one `scrape_broad_area_result` warning.
- [x] (2026-05-25T10:14Z) Fixed encoded meeting-list PDF path matching and recovered Outer Limits Virginia from its GoDaddy-hosted `Meetings%20Updated...pdf`. Persisted 5 active records with zero review flags and exported `snapshots/meetings-2026-05-25T101405Z.json` with `blocked_by_review=0`; NA now has 73,793 active meetings across 675 active sources.
- [x] (2026-05-25T11:31Z) Completed the final concurrent source-specific NA closure pass. Added a direct EASC BMLT service-body mapping plus CT BMLTWF, New River Valley, Luzon, Bermuda, Thailand, and Belarus parsers; persisted 532 net active NA meetings across 7 additional active sources with zero review flags. Exported `snapshots/meetings-2026-05-25T113118Z.json` with `blocked_by_review=0`; NA now has 74,325 active meetings across 682 active sources.

## Surprises & Discoveries

- Observation: NA source discovery is broad in the stored database but ingestion is not.
    Evidence: `sources` has 929 NA rows and 837 local-service-body website rows, while `canonical_meetings` has 2,681 active NA rows from only 6 source IDs.
- Observation: The current live NA locator API rejects the CLI request.
    Evidence: `.venv/bin/python -m app.cli discover-sources --fellowship na --dry-run` failed with HTTP 403 for `https://na.org/wp-content/plugins/meetings-finder/ajax.php`.
- Observation: Existing NA active meetings are geographically narrow.
    Evidence: Joining `canonical_meetings` to `sources` showed all 2,681 active NA meetings under `country='United States'`, and the configured browser sources are New York/New Jersey local sites.
- Observation: The existing classifier does not enable browser scraping for generic meeting pages.
    Evidence: `app/sources/site_classification.py` returns `AdapterType.MANUAL_REVIEW` when `_has_meeting_form` or `_has_meeting_page` succeeds. For NA, this would keep many usable local meeting websites out of `scrape-all`.
- Observation: NA's Cloudflare/WP Engine protection accepts browser same-origin AJAX even when direct `httpx` is blocked.
    Evidence: A live `discover-sources --fellowship na --max-locations 1 --dry-run` logged HTTP 403 for the direct GET, then the Playwright fallback loaded the locator page and returned 25 candidates.
- Observation: BMLT fallback data may not be replayable from page artifacts alone.
    Evidence: Australia imported 750 rows through the BMLT endpoint during browser scraping, but `import-artifacts` on the saved pages saw 0 records for that source because the BMLT fallback response was not saved as extracted page rows.
- Observation: Some NA pages expose downloadable calendar/list links that can fail an otherwise useful browser scrape.
    Evidence: The German source failed after extracting 1,980 rendered rows when the crawler followed `/feed/bmlt2ics/?meeting-id=11088`; Chinook failed after discovering BMLT fallback rows when the crawler followed `?current-meeting-list=7`.
- Observation: NA coverage is now broader but still far from complete.
    Evidence: After the controlled batch and cleanup, active NA meetings are 4,944 across 21 sources and 10 countries. The source registry still has 783 NA local-service-body sources with `adapter_type='unknown'`.
- Observation: After concurrent classification, remaining `unknown` NA sources are not unprocessed; they have classification reasons.
    Evidence: The final classification pass stored 283 sources and left 180 NA `unknown` sources, all with `config.classification.reason`.
- Observation: Browser-crawling direct feed sources is wasteful and can also obscure their structured adapter metadata.
    Evidence: The initial full scrape selected 834 sources and wrapped BMLT sources as `playwright_browser`, even though the BMLT adapter can fetch those feeds directly.
- Observation: Remembered meeting pages can be damaged by generic seeded search heuristics.
    Evidence: South King County's remembered `https://skcna.org/meetings/` page was loaded, then the crawler submitted the site-wide WordPress search for `Washington`, landing on `https://skcna.org/?s=Washington` and extracting 0 rows until search-form submission was disabled for remembered pages.
- Observation: Some BMLT `virtual_meeting_link` fields contain join text rather than URLs.
    Evidence: Greater Orlando BMLT record `8330` contained `virtually on zoom - 404031193`; treating it as `online_url` caused a Pydantic URL validation error and skipped the record.
- Observation: The remaining failed NA sources are mostly not scraper-parser problems.
    Evidence: Concurrent audit bucketed the 33 failed sources as 12 DNS/unresolved host, 9 timeout, 7 TLS certificate common-name, 2 SSL protocol, 1 connection refused, 1 HTTP/2 protocol, and 1 other failure.
- Observation: The remaining zero-record NA sources still contain a meaningful extractor opportunity.
    Evidence: Concurrent artifact scanning found 82 possible missed structured-feed pages and 44 parser-gap candidates among 274 zero-record browser successes; top candidates include Eastern Area Tulsa, Belarus, Ozark Area, Western New York, Azerbaijan, Connecticut, New Brunswick, Colorado, Minnesota, and Sierra Sage sources.
- Observation: Some Crouton/BMLT pages hide their source configuration inside base64 `data:text/javascript` scripts.
    Evidence: NA Colorado's `/meetings/` page only exposed `root_server=https://tomato.bmltenabled.org/main_server` and `service_body=["631"]` after decoding the base64 script tag. The patched detector imported 327 Colorado Region meetings from that endpoint.
- Observation: Embedded BMLT endpoints can be broader than the local source page.
    Evidence: Colorado area pages for Serenity Unlimited and Bringing Freedom East embedded the same service body as the Colorado Region page and imported the same 327 rows. Those duplicate area imports were marked stale; the Colorado Region source remains active.
- Observation: Some hand-built NA sites use repeated classed rows rather than tables or paragraph/list schedules.
    Evidence: Texarkana's page has `.meeting-row` elements with `.meeting-day`, `.meeting-time`, and `.meeting-name`, while the address and venue live in the surrounding `.location-block`. The patched extractor recovered 23 rows from that layout.
- Observation: The sandbox did not have a usable Playwright browser cache in the default home directory.
    Evidence: The first concurrent parser-gap retry failed with `Executable doesn't exist at /home/michaelroddy/.cache/ms-playwright/...`. Installing Chromium with `PLAYWRIGHT_BROWSERS_PATH=/tmp/ms-playwright` allowed the same two-source retry to succeed.
- Observation: Localized meeting pages can pass extractor replay but still be discarded by the crawler if the page detector scores them too low.
    Evidence: Slovenia replayed 8 rows from saved HTML, but the first live retry returned 0 rows because the homepage scored 0.0 and fell below the crawler's local extraction threshold. Adding Slovenian meeting terms and 24-hour dot/h time recognition raised the page score to 1.0 and the retry imported 8 rows.
- Observation: Some remaining parser-gap pages are not recoverable by extractor work because the saved/live pages are errors or unrelated content.
    Evidence: The table/list/paragraph sample included 404 pages for Rivne, El Salvador, Rockland, and Moldova; a WordPress critical error for Quad Cities; a 500 page for Okinawa; and unrelated Chinese web-novel content for Kathmandu.
- Observation: Meeting-list PDFs are recoverable, but generic rendered-text parsing is unsafe for multi-column PDF text.
    Evidence: The first PDF probe showed `pypdf` was not installed, while system `pdftotext` produced usable plain text. Feeding that text through the generic rendered-text parser produced false rows from sidebars and literature columns, so a PDF-specific plain-text extractor was added before enabling live PDF fallback.
- Observation: Some pages link NA literature PDFs whose titles include the word "meetings" but are not schedules.
    Evidence: The zero-record PDF candidate audit found multiple links to NAWS IP #29, "An Introduction to NA Meetings." The link filter now excludes that literature family before selecting meeting-list PDFs.
- Observation: The New Zealand NA meeting picker is not rendered as table rows on the parent page, but it exposes a simple JSON table API behind the iframe.
    Evidence: `https://picker.nzna.org/in-person/SHOW%20ALL/SHOW%20ALL/` and `/online/SHOW%20ALL/SHOW%20ALL/` returned JSON containing an HTML table with 215 total parsed rows.
- Observation: Google Calendar embeds can be usable when the `src` query value maps to a public ICS feed.
    Evidence: CASNA and Southern Idaho calendar iframe `src` values produced public `basic.ics` feeds with weekly recurring VEVENTs. Some other calendar embeds, such as Montreal and Litoral Norte Gaucho, returned private/404 ICS feeds or did not yield meeting records.
- Observation: Direct `?current-meeting-list` source URLs are downloadable PDFs rather than navigable meeting pages.
    Evidence: Playwright navigation raised "Download is starting" for the direct list URLs, but pre-navigation HTTP fetch plus the PDF extractor recovered 410 meetings across nine sources.
- Observation: Some TLS common-name failures are valid meeting sources behind misconfigured certificates.
    Evidence: Retrying CAN Needles with `ignore_https_errors=True` in the browser context recovered 22 meetings from a source that previously failed in the certificate bucket.
- Observation: Official source replacements may still need source-specific parsing.
    Evidence: `https://bahamasna.org/` appears to replace the dead Bahamas NA domain, but its generated current-list endpoint returned a WordPress error and the alternate Bahamas schedule page uses a vertical layout not yet covered by the extractor.
- Observation: Remaining broad retry buckets are now low-yield and timeout-prone.
    Evidence: The first 234-source concurrent retry recovered useful rows early but processed only 78 sources before the 15-minute timeout; many Japanese area pages each crawled to the page cap and still returned zero. The next 50-source quick bucket processed 29 sources before the 12-minute timeout and recovered only two Ukraine sources.
- Observation: Some country and region timezone hints were missing even when source geography was deterministic.
    Evidence: Newly recovered Bahamas, Moldova, and Mexico rows produced 19 `missing_timezone` warnings until `America/Nassau`, `Europe/Chisinau`, and Mexico state hints were added.
- Observation: Japanese NA PDF schedules use localized weekday labels and full-width time separators.
    Evidence: Chubu's linked PDF contained rows such as `月曜`, `月の風`, and `19:00～20:30`. Adding Japanese weekday aliases and `〜`/`～` range normalization let the PDF fallback recover 109 meetings.
- Observation: Generic search-form heuristics can still damage non-remembered directory pages.
    Evidence: NA Ireland pages loaded useful `/na-meetings/...` directories, then the crawler submitted the site-wide WordPress search for `Ireland` and landed on `https://www.na-ireland.org/?s=Ireland` before extraction. Skipping search-form submission when deeper directory links are already available recovered the Ireland sources.
- Observation: Japan area source pages are indexes, while the actual meetings live on day/city child pages.
    Evidence: `https://najapan.org/meeting/kanto/` links to `/meeting/kanto/mon/`, `/tue/`, etc.; the child pages contain paragraph blocks with Japanese labels such as `時間`, `会場`, `場所`, and `形式`.
- Observation: Remembered successful pages can be harmful for multi-page area indexes.
    Evidence: After an initial Japan retry, remembered pages pointed at partial day pages and shared Japan-wide pages. Starting from those remembered pages either stopped before finding the rest of the area or imported the national list under an area source. Japan area sources now always start from the source URL.
- Observation: The first zero-source audit over-counted embed/calendar opportunities.
    Evidence: It treated generic `src=` markup from images, scripts, and WordPress assets as an embed signal, producing 149 `possible_embed_or_calendar` rows. The reusable audit now requires an actual `iframe`, `embed`, or `object` URL with calendar, BMLT, meeting, or schedule terms; the refined audit reduced that bucket to 5 rows.
- Observation: The refined zero-source retry list is useful but now exposes source-specific gaps more than generic crawler gaps.
    Evidence: The 60-source curated retry recovered clean rows from sources such as Pennyrile (205), Western New York (145), Down East (53), South Georgia (32), Central Savannah River (30), Coastal Georgia (28), Greater Morgantown (22), Serenity Unlimited (21), Trinity (6), and Lancaster (3), while many Carolina/PDF and structured-feed candidates still returned zero without source-specific parser/link work.
- Observation: Generic toggle clicks can navigate away from useful WordPress meeting pages.
    Evidence: CRNA schedule pages loaded correctly with embedded BMLT configuration, but the crawler clicked a `role=button` span inside the "New to NA" navigation anchor and ended up on `https://www.crna.org/new-to-na/`. Skipping heuristic clicks inside anchors kept the crawler on the actual schedule pages and recovered CRNA rows.
- Observation: Broad regional meeting tables can be reached from local area pages after link exploration.
    Evidence: The South Coastal source page was stale/404 but linked into broad CRNA pages. The crawler extracted the same 1,852-row regional table that the Carolina Region source should own. The broad-area result quarantine prevents future NA area sources from importing result sets of that size.
- Observation: The remaining high-signal retry buckets have flattened.
    Evidence: After CRNA and the broad-area fixes, the next 37 concurrently retried sources across structured-feed, PDF/printable, parser, and embed buckets recovered only 91 net new meetings from three sources: Marietta (31), Eastern Nebraska (59), and East End (1). The final audit still lists 36 curated candidates, but those now represent already-retried low-yield or source-specific/manual work.
- Observation: There is no remaining generic concurrent import bucket for NA.
    Evidence: The final 36-source dry-run diagnostic produced zero importable rows. The only nonzero extraction was South Coastal's regional-scale CRNA table, which the broad-area guard correctly quarantined. Remaining candidates need source-specific parser work or manual/dead/blocked classification rather than another broad retry.
- Observation: Some old NA World listings point to stale domains, but the current replacement site can still expose recoverable schedules.
    Evidence: `redriverna.org` says it is no longer active and `/meetings/nearest` is a 404, while `www.redriverna.com/sitemap.xml` exposes `/meetings` and a current OklaTex meeting schedule PDF. Source-specific PDF recovery imported 35 Red River occurrence rows split by Oklahoma/Texas source region.
- Observation: Some embed/calendar candidates are location-only and should not be imported as meetings.
    Evidence: Trinidad & Tobago's Webstarts page exposes only a Google My Maps embed. The old My Maps KML endpoint returned 404, and the visible page did not contain meeting days or times, so it remains manual/location-only rather than importing unscheduled place records.
- Observation: Several remaining "zero" pages were not scraper failures; their pages delegated to known BMLT roots with service-body IDs that the generic crawler had not reached.
    Evidence: Downtown Philly, Greater Albuquerque, Hawaii, Lone Star, Mendocino, Monterey, Ozark, and Tejas Bluebonnet all returned scoped JSON directly from BMLT roots and normalized 1,556 rows with zero review flags.
- Observation: Generated current-list PDFs can be regional even when discovered from area sources.
    Evidence: River Coast's page linked to `naflorida.org/?current-meeting-list=1`, which rendered a 460-row Florida Region list covering many Florida areas plus Bermuda and Trinidad and Tobago. Bringing Freedom East's Colorado source rendered a 240-row statewide `nacolorado.org` list. Both are now quarantined for NA area sources.
- Observation: Meeting-list PDFs can be hidden behind encoded file names and generic "Download" link text.
    Evidence: Outer Limits exposed a GoDaddy download button whose anchor text was only `Download`, while the actual href path contained `Meetings%20Updated%2012%205%2025.pdf`. Decoding the path before keyword matching let the existing PDF text extractor recover 5 current meetings.

## Decision Log

- Decision: Use a dedicated NA ExecPlan.
    Rationale: NA coverage work now includes source discovery repair, source classification, browser scraping, possible extractor changes, review cleanup, and snapshot export. This is a significant feature pass under the repository's `AGENTS.md` guidance.
    Date/Author: 2026-05-24 / Codex.
- Decision: Full NA scrape runs must use bounded source-level concurrency.
    Rationale: The user explicitly requested concurrent scraping for all sources. The CLI already supports `scrape-all --concurrency`, which parallelizes sources while preserving each source's artifact directory and per-source crawler behavior.
    Date/Author: 2026-05-24 / Codex.
- Decision: Do not run a full NA scrape before discovery repair and source classification.
    Rationale: Only 7 NA sources are currently configured for browser scraping. Running `scrape-all` immediately would mostly repeat the existing New York-only data instead of expanding NA coverage.
    Date/Author: 2026-05-24 / Codex.
- Decision: Route meeting pages and meeting forms to the browser scraper during classification.
    Rationale: The browser crawler now has the shared AA/CA extraction logic for rendered text, forms, search pages, and common meeting page paths. Keeping these sources at `manual_review` prevents `scrape-all` from attempting them at all.
    Date/Author: 2026-05-24 / Codex.
- Decision: Treat `UTC` from BMLT rows as missing when better source/location geography exists.
    Rationale: Australian BMLT rows used `UTC` despite carrying country, state, postal code, or coordinates. Keeping `UTC` created noisy missing-timezone warnings; replacing it only when geography is available preserves ambiguous online rows for review.
    Date/Author: 2026-05-24 / Codex.
- Decision: Skip downloadable calendar/list URLs during crawling.
    Rationale: Calendar exports and generated list downloads are not meeting directory pages. Following them caused Playwright download errors after useful rows had already been extracted.
    Date/Author: 2026-05-24 / Codex.
- Decision: Skip classified unknown sources during `scrape-all` unless explicitly requested.
    Rationale: Once classification has recorded that a source has no detectable feed or meeting page, full scrape should not spend browser time on it by default. The new `--include-classified-unknown` option keeps an escape hatch for audit/retry work.
    Date/Author: 2026-05-24 / Codex.
- Decision: Direct feed adapters should be ingested directly during `scrape-all`.
    Rationale: BMLT and Meeting Guide are structured feeds; launching a browser to rediscover them is slower and less reliable than using the adapters already configured on the source.
    Date/Author: 2026-05-24 / Codex.
- Decision: Remembered meeting pages are a refresh shortcut, not an unconditional replacement for discovery.
    Rationale: Reusing `successful_pages` and `last_successful_page_url` makes repeat scrapes faster, but stopping after a sharply lower record count could incorrectly stale meetings. The crawler now falls back to normal discovery when remembered pages fail, return zero, or show a large count drop.
    Date/Author: 2026-05-24 / Codex.
- Decision: Do not submit seeded search forms on remembered meeting pages.
    Rationale: Remembered pages are already known meeting pages, so a generic source-region search can navigate away from the useful page before extraction. Harmless expansion clicks still run, but search-form submission is limited to normal discovery pages.
    Date/Author: 2026-05-24 / Codex.
- Decision: Keep invalid BMLT virtual-meeting text as connection info instead of dropping the row.
    Rationale: The canonical schema requires `online_url` to be a valid HTTP URL, but free text such as Zoom IDs is still useful join information. Storing that text in `phone_join_info` preserves the meeting while keeping URL validation strict.
    Date/Author: 2026-05-24 / Codex.
- Decision: Decode Crouton/BMLT data-script config before deciding whether browser scrape fallback can use BMLT.
    Rationale: Several WordPress performance plugins move inline Crouton config into base64 data-script URLs. Decoding those scripts lets the existing BMLT adapter do structured ingestion instead of relying on an empty rendered DOM.
    Date/Author: 2026-05-24 / Codex.
- Decision: Do not keep area-level imports when the embedded endpoint clearly returns the same region-wide BMLT feed.
    Rationale: It is better to keep the region source as the owner for those rows than to duplicate the same meeting set under multiple area source IDs.
    Date/Author: 2026-05-24 / Codex.
- Decision: Add a narrow classed-row extractor instead of loosening generic text-block parsing.
    Rationale: `.meeting-row` style schedules provide explicit day/time/name fields and nearby venue/address context, so they can be handled safely without increasing false positives from service hours or event text.
    Date/Author: 2026-05-24 / Codex.
- Decision: Normalize localized weekday labels to English during extraction.
    Rationale: The downstream static HTML adapter already normalizes English weekday names to occurrences. Returning English day names from Russian and Slovenian schedule layouts lets recovered rows normalize without adding source-specific downstream adapters.
    Date/Author: 2026-05-24 / Codex.
- Decision: Use PDF fallback only for strong meeting-list/schedule links and keep source pages classified as browser sources.
    Rationale: Generic PDF ingestion remains source-specific and risky, but browser pages with explicit "meeting list", "meeting schedule", or "where and when" PDF links can be recovered safely enough with a bounded same-page fallback. Literature, service, event, minutes, and newsletter PDFs remain excluded.
    Date/Author: 2026-05-24 / Codex.
- Decision: Treat Google Calendar embeds as meeting sources only for current weekly recurring events.
    Rationale: Calendar feeds often contain events, speaker jams, service meetings, old cancelled meetings, and one-off activities. Restricting extraction to `FREQ=WEEKLY` records without expired `UNTIL` dates and filtering obvious event/service terms reduces false positives while recovering calendar-backed meeting schedules.
    Date/Author: 2026-05-24 / Codex.
- Decision: Allow the configured source URL itself even when it contains skipped download-style query keys.
    Rationale: Query values such as `current-meeting-list` are unsafe for link exploration, but when the registry source itself points there it is the canonical meeting list. The crawler now treats the source URL as allowed while still filtering discovered download links.
    Date/Author: 2026-05-24 / Codex.
- Decision: Fetch direct downloadable meeting-list PDFs before browser navigation.
    Rationale: Browser navigation to a PDF download can fail before extraction, while the existing HTTP/PDF path can recover records and save the result as a normal scraped page artifact.
    Date/Author: 2026-05-24 / Codex.
- Decision: Add repeated `scrape-all --source-id` filtering for retry buckets.
    Rationale: Offset and status filters are too coarse once only specific parser/replacement candidates remain. Source-ID filtering lets curated sets run concurrently through the normal scrape/import path while avoiding already recovered sources.
    Date/Author: 2026-05-24 / Codex.
- Decision: Prefer directory-link crawling over generic site-search submission when both are present on a credible meeting page.
    Rationale: Site-wide search forms are useful on sparse landing pages, but on pages already exposing meeting-directory links they can navigate away from the higher-signal content before extraction.
    Date/Author: 2026-05-24 / Codex.
- Decision: Constrain `najapan.org/meeting/<area>/...` crawls to their own area branch.
    Rationale: The global WordPress menu exposes every Japan area plus the national PDF. Without branch scoping, low-cap area retries can import shared national rows under local area source IDs.
    Date/Author: 2026-05-24 / Codex.
- Decision: Make zero-source audit repeatable through the CLI before more broad retries.
    Rationale: The one-off audit was useful but over-broad, especially for embed/calendar detection. A reusable command writes `audit.json`, `audit.md`, `retry-source-ids.txt`, and a generated retry command so future passes can be reproduced and compared.
    Date/Author: 2026-05-25 / Codex.
- Decision: Quarantine very large NA area-source scrape results.
    Rationale: NA areas normally should not own hundreds or thousands of rows. If an area source produces 500 or more scraped rows, the safer default is to treat it as a broad regional result and avoid importing it under the local source ID. Region sources are still allowed to own regional-scale results.
    Date/Author: 2026-05-25 / Codex.
- Decision: Add verified source-specific BMLT endpoint mappings for the remaining structured-feed candidates instead of expanding generic browser crawling.
    Rationale: The endpoints are deterministic, faster, and scopeable by service body. The dry-run proved they normalize cleanly with no review flags, while prior generic browser diagnostics returned zero for the same sources.
    Date/Author: 2026-05-25 / Codex.
- Decision: Quarantine generated `current-meeting-list` PDF results of 200 or more rows for NA area sources.
    Rationale: Legitimate area printable lists recovered in this pass were much smaller, while the new 240-row and 460-row candidates were clearly region-wide lists reached from area pages. The guard prevents concurrent retries from importing regional records under local area source IDs.
    Date/Author: 2026-05-25 / Codex.
- Decision: Decode URL-encoded PDF paths before applying meeting-list keyword filters.
    Rationale: Encoded spaces are common in hosted download URLs. Decoding only the path preserves the existing conservative keyword and negative-term checks while allowing names such as `Meetings%20Updated...pdf` to match.
    Date/Author: 2026-05-25 / Codex.
- Decision: Finish the remaining recoverable NA audit rows with source-specific adapters instead of broad crawler loosening.
    Rationale: The last recoverable rows each had a clear source shape: BMLT service body, BMLTWF JSON, stacked schedule page, Weebly schedule, WordPress schedule, area-page index, or Russian schedule tables. Narrow adapters recovered clean rows with zero review flags without increasing generic false-positive risk.
    Date/Author: 2026-05-25 / Codex.

## Outcomes & Retrospective

Discovery repair, classifier changes, a controlled concurrent scrape batch, full NA classification, full concurrent scrape/import, targeted concurrent failed/zero retries, BMLT data-script recovery, classed-row and localized-table parser recovery, meeting-list PDF recovery, Japanese PDF and paragraph-page recovery, iframe/embed recovery, source-replacement recovery, source-ID filtered retry buckets, directory-link protection for generic search forms, Japan area branch scoping, repeatable zero-source audit, broad-area quarantine, timezone cleanup, source-specific direct BMLT recovery, linked current-list PDF recovery, encoded PDF path recovery, final source-specific parser recovery, and snapshot export are implemented and validated. NA active meetings increased from 2,681 at baseline to 74,325, and active NA source coverage increased from 6 sources to 682 sources. `snapshots/latest.json` now contains 173,244 total active meetings, and the latest export is `snapshots/meetings-2026-05-25T113118Z.json` with `blocked_by_review=0`. Remaining NA follow-up work is limited to unrecoverable/manual or broad-risk sources documented in `docs/na_completion_audit_2026-05-25.md`: three broad regional duplicate-risk current-list/table sources and four manual/stale/blocked sources.

## Context and Orientation

This repository is `/home/michaelroddy/repos/recovery-meeting-ingestion`. It is a Python service that discovers recovery meeting sources, scrapes source websites, normalizes scraped rows into canonical meetings, stores review flags, and exports `snapshots/latest.json` for SoberSpace.

The command entry point is `app/cli.py`. NA source discovery lives in `app/sources/na_world_services.py`. Source classification lives in `app/sources/site_classification.py`; classification means probing a source URL to decide which adapter should fetch it. Browser scraping lives in `app/scraping/` and is used through the `playwright_browser` adapter. The database repository code is `app/storage/repositories.py`. Snapshot export is `app/export/snapshot.py`.

A source is a row in the `sources` table. A local-service-body source is a local NA area, region, or country website. A canonical meeting is a normalized row in `canonical_meetings` that can be exported. A review flag is a warning or error row in `review_flags`; open errors block publication, while warnings need audit. A scrape artifact is a saved per-source directory under `scrape_artifacts/` containing fetched pages, screenshots, and a summary JSON that can be replayed later.

The local database URL is the default from `app/config.py`: `postgresql:///recovery_meeting_ingestion_dev`. The virtual environment is `.venv/`. Playwright browser binaries are present under `.playwright-browsers/`.

## Plan of Work

First, repair NA discovery refresh. Start in `app/sources/na_world_services.py`. The current implementation posts directly to the WordPress meetings-finder AJAX endpoint with only static headers. If NA now requires cookies or a nonce from the public locator page, update `NaWorldServicesDiscovery.discover` to fetch the locator page first, preserve the same `httpx.AsyncClient` session, parse any obvious nonce or action fields needed by the AJAX endpoint, and then post the search/listing requests. If direct HTTP remains blocked, add a browser-backed fallback that uses the public locator page to collect the JSON responses or page state. Add or update tests in `tests/test_discovery.py` for parsing any new token/state logic, using fixture strings rather than live network.

Second, classify NA web sources. The existing `SourceProbeClassifier` already detects Meeting Guide and BMLT JSON feeds, but it currently marks generic meeting forms and meeting pages as `manual_review`. For NA, AA, and CA browser scraping has matured enough that local-service-body sources with meeting pages should become `playwright_browser` with `requires_browser=True`, while phone-only and PDF sources remain manual. Make this change conservatively in `app/sources/site_classification.py` and add tests in `tests/test_site_classification.py`.

Third, run a classification pass for NA unknown sources:

    .venv/bin/python -m app.cli classify-sources --fellowship na --limit 50

Inspect the output. If it looks correct, run the persisted pass without a limit or in several chunks. Check adapter counts afterward:

    psql postgresql:///recovery_meeting_ingestion_dev -c "SELECT source_type, adapter_type, requires_browser, COUNT(*) FROM sources WHERE fellowship='na' GROUP BY 1,2,3 ORDER BY COUNT(*) DESC;"

Fourth, run a controlled concurrent scrape batch. Use a timestamped artifact directory and bounded concurrency:

    PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers \
      .venv/bin/python -m app.cli scrape-all \
      --fellowship na \
      --limit 30 \
      --max-pages-per-source 12 \
      --concurrency 4 \
      --output-dir scrape_artifacts/na-controlled-YYYYMMDDTHHMMSSZ \
      --no-dry-run

Inspect source summaries, records extracted, review flags, and active meeting count changes. Do not run a full scrape until the controlled batch shows that common NA pages can be extracted without obvious source-drop errors.

Fifth, patch extractor gaps as they appear. Likely files are `app/scraping/extract_meetings.py`, `app/scraping/browser_crawler.py`, `app/scraping/meeting_page_detector.py`, and `app/scraping/meeting_vocabulary.py`. Keep each patch focused and add tests in `tests/test_scraping_primitives.py` or the relevant existing test file.

Finally, run the full concurrent NA scrape/import. Use `--concurrency` with a conservative value such as 4 or 8, depending on controlled-batch reliability:

    PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers \
      .venv/bin/python -m app.cli scrape-all \
      --fellowship na \
      --max-pages-per-source 12 \
      --concurrency 8 \
      --output-dir scrape_artifacts/na-full-YYYYMMDDTHHMMSSZ \
      --no-dry-run

Afterward, audit open review flags and export:

    psql postgresql:///recovery_meeting_ingestion_dev -c "SELECT COALESCE(cm.fellowship, s.fellowship), rf.code, rf.severity, COUNT(*) FROM review_flags rf LEFT JOIN canonical_meetings cm ON cm.id = rf.canonical_meeting_id LEFT JOIN sources s ON s.id = rf.source_id WHERE rf.status='open' GROUP BY 1,2,3 ORDER BY 1,3,4 DESC;"
    .venv/bin/python -m app.cli export-snapshot --no-dry-run

## Concrete Steps

All commands are run from `/home/michaelroddy/repos/recovery-meeting-ingestion`.

Baseline commands already run:

    psql postgresql:///recovery_meeting_ingestion_dev -c "SELECT source_type, adapter_type, requires_browser, COUNT(*) FROM sources WHERE fellowship='na' GROUP BY 1,2,3 ORDER BY COUNT(*) DESC;"
    psql postgresql:///recovery_meeting_ingestion_dev -c "SELECT COUNT(*) AS na_sources FROM sources WHERE fellowship='na'; SELECT COUNT(*) AS na_active_meetings FROM canonical_meetings WHERE fellowship='na' AND status='active'; SELECT COUNT(DISTINCT source_id) AS na_sources_with_active_meetings FROM canonical_meetings WHERE fellowship='na' AND status='active';"
    .venv/bin/python -m app.cli discover-sources --fellowship na --dry-run

Observed baseline:

    NA sources: 929
    NA local-service-body website sources: 837
    NA phone/manual-review sources: 92
    NA configured playwright_browser sources: 7
    NA active meetings: 2681
    NA sources with active meetings: 6
    Live NA discovery dry-run: HTTP 403 from the locator AJAX endpoint

## Validation and Acceptance

Validation must happen at each milestone.

For discovery repair, run:

    .venv/bin/python -m app.cli discover-sources --fellowship na --dry-run

Acceptance: the command exits successfully and reports a candidate count rather than HTTP 403.

For classification changes, run:

    .venv/bin/ruff check app tests
    .venv/bin/pytest tests/test_site_classification.py tests/test_discovery.py -q
    .venv/bin/mypy app

Acceptance: tests pass, and a dry-run or limited classification pass shows meeting page/form sources becoming `playwright_browser` rather than `manual_review` when appropriate. This has been demonstrated for the first 50-source NA classification batch.

For controlled scraping, run the controlled concurrent command from the plan. Acceptance: the command completes, writes an artifact directory, extracts meetings from more than the existing New York-only source set, and does not leave open `source_large_drop` errors.

The first controlled concurrent scrape has met this acceptance bar. It wrote `scrape_artifacts/na-controlled-20260524T152600Z`, and after targeted cleanup plus focused reruns, `snapshots/latest.json` contains `na=4944` meetings and `blocked_by_review=0`.

For final scraping, run the full concurrent command, audit review flags, and export. Acceptance: `export-snapshot --no-dry-run` reports `blocked_by_review: 0`, `snapshots/latest.json` is refreshed, and NA active meeting count and/or source coverage are materially broader than the baseline.

Final acceptance is met. The latest export is `snapshots/meetings-2026-05-25T113118Z.json` with `blocked_by_review: 0`. The final full validation run passed:

    .venv/bin/ruff check app tests
    .venv/bin/mypy app
    .venv/bin/pytest -q

Pytest reported 217 passed and 13 skipped.

## Idempotence and Recovery

Discovery and classification upserts are safe to rerun; they update source metadata by normalized URL and fellowship. Scrape commands write timestamped artifact directories. If a scrape is interrupted, resume with a new artifact directory and use source metadata, artifact summaries, and `--offset` only with care because status filtering can shift numeric offsets. Prefer checking which source IDs already have successful import runs.

The importer replaces source review flags for a source and can mark meetings stale if a successful scrape returns fewer records. For controlled batches, inspect record counts before broad runs. Failed scrapes should persist metadata without replacing canonical meetings, based on existing AA fixes.

## Artifacts and Notes

Important baseline transcript:

    source_type/local_service_body adapter_type/unknown requires_browser/f count: 830
    source_type/phone adapter_type/manual_review requires_browser/f count: 92
    source_type/local_service_body adapter_type/playwright_browser requires_browser/t count: 7
    active NA meetings: 2681
    sources with active NA meetings: 6

Live discovery failure transcript:

    HTTP Request: POST https://na.org/wp-content/plugins/meetings-finder/ajax.php "HTTP/1.1 403 Forbidden"
    HTTPStatusError: Client error '403 Forbidden' for url 'https://na.org/wp-content/plugins/meetings-finder/ajax.php'

## Interfaces and Dependencies

Use the existing libraries already in the project: `httpx` for HTTP requests, `selectolax` for lightweight HTML parsing, Typer for CLI commands, Playwright through the existing browser scraper for dynamic sites, and psycopg for database access.

The key public interfaces are:

In `app/sources/na_world_services.py`, keep:

    class NaWorldServicesDiscovery:
        async def discover(self, max_locations: int | None = None) -> list[SourceCandidate]
        def parse_html(self, html: str) -> list[SourceCandidate]

In `app/sources/site_classification.py`, keep:

    class SourceProbeClassifier:
        async def classify(self, source: Source) -> ClassificationResult

If browser classification is added, it should update `Source.adapter_type` to `AdapterType.PLAYWRIGHT_BROWSER` and `requires_browser` to `True` for suitable local-service-body meeting websites.

## Revision Notes

2026-05-24: Initial plan created because the user asked to proceed with NA coverage work and explicitly required concurrent scraping for all sources.

2026-05-24: Updated after implementing NA discovery fallback and browser classification for meeting pages/forms. This records the direct evidence and keeps the next steps focused on persisted classification and controlled scraping.

2026-05-24: Updated after the first controlled concurrent scrape and cleanup pass. This records the newly imported NA coverage, the BMLT/artifact replay caveat, the download-link crawler fix, and the remaining need for a full concurrent scrape.

2026-05-25: Added a source-specific direct AJAX parser for Brazil `na.org.br` `cade-o-grupo` meeting pages. The parser bypasses browser UI interaction, scopes area sources by metadata city when present, and imported 1,261 active occurrence records for `na-57cee7d3ba6b` plus 44 for `na-0311a0916a61` with zero review flags. Current NA active coverage is 71,872 meetings across 655 sources; exported snapshot `snapshots/meetings-2026-05-25T011102Z.json` has `blocked_by_review: 0`.

2026-05-25: Continued the parser-gap group concurrently. Added direct BMLT imports for Ocean Gateway (`na-a78c156fa126`, service body `38`, 33 active records) and SAMMA (`na-f89bb33e4f09`, service body `162`, 16 active records), plus a Ukrainian WordPress block parser for `na-be52cc6d882d` (11 active records). All three persisted with zero review flags. UK Farsi remains blocked/manual because `meetings.ukna.org` and `online.ukna.org` return Cloudflare challenge pages and the accessible UKNA page does not expose a Farsi/Persian feed. Current NA active coverage is 71,932 meetings across 658 sources; exported snapshot `snapshots/meetings-2026-05-25T012220Z.json` has `blocked_by_review: 0`.

2026-05-25: Generalized linked `current-meeting-list` PDF recovery so browser pages can fetch printable list URLs discovered in anchors or button `data-url` attributes. This recovered Just for Today Kansas (`na-3e653e4288a3`, 60 records), Southern Oregon (`na-90efe8899be9`, 40 records), and Appalachian/CVAANA (`na-80b945d48ccb`, 22 records) with zero review flags. Current NA active coverage is 73,661 meetings across 672 sources; exported snapshot `snapshots/meetings-2026-05-25T091323Z.json` has `blocked_by_review: 0`.

2026-05-25: Moved the local-page low-score extraction threshold ahead of embed/PDF fallback so weak rendered-page candidates do not suppress stronger linked meeting-list recovery. This recovered Palm Coast (`na-3a9a90702ff7`, 81 records) and Rock River (`na-c61bddc3eff3`, 46 records) with zero review flags. Current NA active coverage is 73,788 meetings across 674 sources; exported snapshot `snapshots/meetings-2026-05-25T094825Z.json` has `blocked_by_review: 0`.

2026-05-25: Completed the final source-specific closure pass concurrently. Added EASC direct BMLT service body `42`, CT BMLTWF JSON parsing, and parsers for New River Valley, Luzon, Bermuda, Thailand, and Belarus. The pass persisted 532 net active NA meetings across 7 additional active sources with zero review flags. Current NA active coverage is 74,325 meetings across 682 sources; exported snapshot `snapshots/meetings-2026-05-25T113118Z.json` has `blocked_by_review: 0`.

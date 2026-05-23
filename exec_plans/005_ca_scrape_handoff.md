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

## Resume Update - 2026-05-21

Implemented the first parser-gap fixes from artifact triage:

- TSML JSON feeds from `wp-admin/admin-ajax.php?action=meetings` are now parsed directly when crawled.
- Browser crawler discovery now includes alternate JSON meeting-feed links.
- Browser crawler now short-circuits TSML meeting pages by fetching the JSON feed from the already-open page when available, so it can stop after the full feed instead of spending crawl slots on rendered TSML views.
- Rendered TSML tables now extract visible rows by reading weekday/time from TSML row metadata.
- Accordion-style day panels now extract meeting blocks with `Location:` lines.
- Attendance option metadata from scraper payloads now influences normalized meeting type.

Saved artifact spot checks now extract:

- France TSML page: `5` records from `ca-e3b4e7bd99d3/pages/002-a90ea18417.html`
- Scotland TSML page: `30` records from `ca-c6e4f7eaacad/pages/002-241750885e.html`
- Southern Ontario TSML page: `24` records from `ca-4ad24f63e321/pages/002-bc043664dc.html`
- BC accordion page: `18` records from `ca-73df240e1b14/pages/002-0aff7e68b0.html`

Validation after these changes:

- `.venv/bin/ruff check app tests`
- `.venv/bin/mypy app`
- `.venv/bin/pytest -q`

Latest full test result:

- `85 passed, 10 skipped`

Latest CA-wide dry run after TSML speed changes:

```bash
PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers \
  .venv/bin/python -m app.cli scrape-all \
  --fellowship ca \
  --max-pages-per-source 6 \
  --output-dir scrape_artifacts/ca-wide-dry-run-20260521-fast-tsml
```

Dry run comparison versus `scrape_artifacts/ca-wide-dry-run-20260521`:

- Total records: `1,416` -> `2,619`
- Total pages visited: `281` -> `244`
- Sources with records: `63` -> `68`
- Zero-record successful sources: `56` -> `52`
- Failed sources: `4` -> `3`
- Max-page zero-record sources: `14` -> `10`
- Approx artifact elapsed time: `1,967s` -> `1,846s`

Notable TSML/feed wins:

- Kent: `871` records in `2` pages from `http://www.cakent.org/`
- Scotland: `212` records in `1` page from `http://www.cascotland.org.uk/`
- Southern Ontario: `140` records in `1` page from `https://www.ca-on.org/`
- LA: `83` records in `1` page from `http://www.ca4la.org/`
- Utah: previously timed out, now `19` records in `1` page from `https://cautah.org`

Remaining hard failures:

- `ca-23b0bd1f769e` - `http://www.northtexasca.com/` - DNS failure
- `ca-35a80b91e362` - `http://cahongkong.com/` - redirect loop
- `ca-e2760999c192` - `http://camaine-com.webs.com/` - DNS failure

Next speed/coverage target:

- Cut false-positive guessed meeting paths that return 404/Page Not Found so sources like Quebec, Russia, Minnesota, Denmark, Oklahoma, Cyber Serenity, Norway, and Connecticut do not spend the full 6-page cap on dead guessed URLs.
- Then inspect real two-page zero-yield parser gaps like Jakarta, New Jersey, San Fernando Valley, and Wisconsin.

404 guessed-path speed pass:

- Common guessed meeting paths now dedupe trailing-slash variants before enqueueing.
- If the crawler is using guessed common meeting paths and sees two clear not-found pages, it prunes the remaining guessed paths and disables broad generic fallback for that source.
- This only applies after the crawler had to guess meeting paths; discovered links from the source page are not pruned this way.

Targeted verification:

- Minnesota `ca-8f845cc302e6`: `6` pages -> `3` pages
- Oklahoma `ca-60973398a3f3`: `6` pages -> `3` pages
- Cyber Serenity `ca-515a0089a544`: `6` pages -> `3` pages

Minnesota follow-up:

- The Minnesota meeting info is on the landing page, but Wix rendered it into body text that the previous fallback skipped as one oversized block.
- Added sequence-based rendered-text extraction for `name -> day/time -> details` patterns.
- Minnesota `ca-8f845cc302e6` now extracts `4` records from the landing page and stops after `1` page.

Validation after 404 speed pass:

- `.venv/bin/ruff check app tests`
- `.venv/bin/mypy app`
- `.venv/bin/pytest -q`
- Latest full test result: `88 passed, 10 skipped`

Thailand/homepage follow-up:

- Thailand confirmed the same class of issue as Minnesota: usable meeting info is on the local homepage (`https://cathailand.org/`), not on the generic CA world-service listing page.
- The registry/artifacts include both the placeholder world-service listing (`https://ca.org/meetings/thailand/`) and the discovered local source (`https://cathailand.org`).
- `scrape-all` now skips CA world-service listing sources when a discovered local source already has matching `config.metadata.world_source`. This avoids spending crawl budget on placeholder pages that are only pointers to local sites.
- Direct-listing extraction now carries schedule context across adjacent homepage paragraphs. This handles patterns like `Chiang Mai Group` + `Saturday 4.30pm` in one paragraph followed by venue/address/contact paragraphs.
- Time extraction now handles dot/semicolon/compact times such as `4.30pm`, `9.30am`, `930am`, and ranges such as `5.30 to 6.30pm`.
- Saved Thailand artifact extraction improved from `11` records with bad `30pm`/`30am` times to `13` homepage records with normalized times.

Validation after Thailand/homepage pass:

- `.venv/bin/ruff check app tests`
- `.venv/bin/mypy app`
- `.venv/bin/pytest -q`
- Latest full test result: `90 passed, 10 skipped`
- Fixture scrape verification against the saved Thailand page succeeded with `pages_visited: 1`, `records_extracted: 13`, `records_fetched: 13`, `candidates_normalized: 13`.
- Live targeted Playwright scrape could not be rerun because the local Playwright browser cache path is missing in this environment (`/home/michaelroddy/.cache/ms-playwright` does not exist). Saved-artifact parser verification succeeded against `scrape_artifacts/ca-wide-dry-run-20260521-fast-tsml/ca-d57287ec55b9/pages/001-d57287ec55.html`.

Norway/landing-page stop follow-up:

- Norway confirmed another landing-page schedule pattern. The local source `https://www.ca-norge.no` previously visited `14` pages and extracted `0`, even though the homepage contains the meeting list.
- Added inline landing-page schedule extraction for compact blocks such as `CA OSLO - KRYPTEN mandag kl. 20-21 ... fredag kl. 20-21 ... Holtegata 15, 0259 Oslo`.
- Added Norwegian `kl.` time/range handling and `fredag` schedule normalization.
- Crawler stop behavior now stops after any valid meeting found on a root landing page, not only record-rich landing pages. This is the intended behavior for Minnesota/Thailand/Norway-style homepages.
- Fixture scrape verification against the saved Norway page succeeded with `pages_visited: 1`, `records_extracted: 6`, `records_fetched: 6`, `candidates_normalized: 6`.
- Latest full test result after this pass: `92 passed, 10 skipped`.

CA-wide dry run after landing-stop changes:

```bash
PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers \
  .venv/bin/python -m app.cli scrape-all \
  --fellowship ca \
  --max-pages-per-source 6 \
  --output-dir scrape_artifacts/ca-wide-dry-run-20260521-landing-stop
```

Comparison versus `scrape_artifacts/ca-wide-dry-run-20260521-fast-tsml`:

- Sources scraped: `123` -> `100`
- World-service placeholder listings skipped because local sources exist: `23`
- Total records: `2,619` -> `2,543`
- Total pages visited: `244` -> `167`
- Sources with records: `68` -> `79`
- Zero-record successful sources: `52` -> `18`
- Failed sources: `3` -> `3`
- Max-page zero-record sources: `10` -> `2`
- Artifact size: `178M` -> `145M`

Confirmed wins:

- Norway `ca-4a2c9ec70003`: `0` records / `6` pages -> `6` records / `1` page.
- Thailand `ca-d57287ec55b9`: `11` records / `1` page -> `13` records / `1` page.
- Minnesota `ca-8f845cc302e6`: `0` records / `6` pages -> `2` records / `1` page.
- Australia `ca-26f3ea8a5914`: `3` records / `6` pages -> `7` records / `1` page.

Caution before import:

- A follow-up selective stop rule was added after this run: landing-page records only stop the crawl when there is no deeper same-site meeting-directory link left to crawl. Self-links such as Thailand's homepage `Meetings` link are ignored.
- Targeted verification after the selective rule:
  - New York `ca-e53b161d1e98`: `2` pages, `27` records. This fixes the preview-page regression where the homepage had only `2` records and linked to `/ca-new-york-meetings/#/`.
  - Illinois `ca-ffc813f90d4c`: `2` pages, `11` records. This fixes the preview-page regression where the homepage had only `1` record and linked to `/meetings`.
  - Norway `ca-4a2c9ec70003`: still `1` page, `6` records.
  - Thailand `ca-d57287ec55b9`: still `1` page, `13` records.
  - Minnesota `ca-8f845cc302e6`: still `1` page, `2` records.
- Validation after selective stop rule:
  - `.venv/bin/ruff check app tests`
  - `.venv/bin/mypy app`
  - `.venv/bin/pytest -q`
  - Latest full test result: `94 passed, 10 skipped`
- CA-wide dry run after selective stop rule:

```bash
PLAYWRIGHT_BROWSERS_PATH=/home/michaelroddy/repos/recovery-meeting-ingestion/.playwright-browsers \
  .venv/bin/python -m app.cli scrape-all \
  --fellowship ca \
  --max-pages-per-source 6 \
  --output-dir scrape_artifacts/ca-wide-dry-run-20260521-selective-landing-stop
```

Selective run comparison:

- `fast-tsml`: `123` sources, `2,619` records, `244` pages, `68` sources with records, `52` zero-successes, `3` failures, `10` max-page zero-successes.
- `landing-stop`: `100` sources, `2,543` records, `167` pages, `79` sources with records, `18` zero-successes, `3` failures, `2` max-page zero-successes.
- `selective-landing-stop`: `100` sources, `2,673` records, `189` pages, `78` sources with records, `19` zero-successes, `3` failures, `3` max-page zero-successes.
- On the 100 sources common to the selective run and `fast-tsml`, records improved `2,592` -> `2,673` and pages dropped `221` -> `189`.
- Artifact size: `fast-tsml 178M`, `landing-stop 145M`, `selective-landing-stop 160M`.

Selective run confirmed recoveries:

- New York `ca-e53b161d1e98`: back to `27` records in `2` pages.
- Illinois `ca-ffc813f90d4c`: back to `11` records in `2` pages.
- Nebraska `ca-a27a5c3933d7`: back to `40` records in `2` pages.
- Utah `ca-6e8cc57bd9cf`: improved `19` -> `44` records in `2` pages.
- Norway/Thailand/Minnesota still stop at `1` page with records.

Remaining caution before import:

- Some regional sites still have record drops versus `fast-tsml` because the crawl stops after one regional page or fewer regional branches:
  - Ohio `ca-1604697fd134`: `50` -> `29` records.
  - Florida `ca-6d96eea96ed1`: `28` -> `14` records.
  - Arkansas `ca-978cdf62a16a`: `16` -> `3` records.
  - Colorado `ca-612a2af62208`: `45` -> `37` records.
- Remaining failures are unchanged source/URL problems:
  - North Texas DNS failure.
  - Hong Kong redirect loop.
  - Maine DNS failure.
- Remaining max-page zero-success sources:
  - Connecticut `ca-041da33d75c7`
  - Sweden `ca-4f169a540b19`
  - Central UK `ca-609577b509b9`

Next recommendation:

- Before real import, inspect/fix the regional-branch drops for Ohio, Florida, Arkansas, and Colorado, then rerun a final dry comparison.

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

## 2026-05-22 Follow-up

Implemented two crawl-speed/completeness fixes after the selective landing-page stop run:

- Queue-aware branch continuation: a page with records no longer stops the source crawl while sibling meeting-branch URLs are still pending. Targeted checks recovered the regional branch drops:
  - Florida `ca-6d96eea96ed1`: `28` records.
  - Arkansas `ca-978cdf62a16a`: `16` records.
  - Colorado `ca-612a2af62208`: `46` records.
- TSML feed shortcuts:
  - Ohio `ca-1604697fd134` now discovers the `data-src` feed `https://caws-api.azurewebsites.net/api/v1/meetings-tsml?area=Ohio` and extracts `79` records in `1` page instead of relying on the unstable rendered table (`29`-`50` visible rows).
  - Filtered TSML links like `?tsml-district=kent` are converted directly to filtered JSON feeds such as `wp-admin/admin-ajax.php?action=meetings&district=kent`. Kent `ca-75af35f3d1db` improved from a stale old-code run of `20` pages / `871` normalized records to `2` pages / `36` Kent records.

Validation after these fixes:

- `.venv/bin/ruff check app tests`: passed.
- `.venv/bin/mypy app`: passed.
- `.venv/bin/pytest -q`: `98 passed, 10 skipped`.

Operational note:

- A full dry run started before the filtered TSML-link queue fix was still running with old in-memory code, so its Kent/UK aggregate should not be used as the final import comparison. Use the targeted post-fix checks above, then rerun a fresh CA-wide dry run from a clean command for the final import gate.

Fresh bounded CA-wide dry run from current code:

```bash
PLAYWRIGHT_BROWSERS_PATH=/tmp/ms-playwright \
  timeout 2400s .venv/bin/python -m app.cli scrape-all \
  --fellowship ca \
  --max-pages-per-source 6 \
  --output-dir scrape_artifacts/ca-wide-dry-run-20260522-final-fast
```

Result:

- Exit code: `0`.
- Sources: `100` (`23` shadowed world-service listing placeholders skipped).
- Pages visited: `199`.
- Records extracted: `2,356`.
- Records fetched: `2,341`.
- Candidates normalized: `2,340`.
- Review flags: `1,770`.
- Failed sources: `3`.
- Zero-record successes: `18`.
- Sources at the 6-page cap: `10`.

Known failures in the fresh run:

- Hong Kong `ca-35a80b91e362`: redirect loop.
- Maine `ca-e2760999c192`: DNS failure.
- North Texas `ca-23b0bd1f769e`: DNS failure.

Important full-run confirmations:

- Ohio `ca-1604697fd134`: `79` records / `1` page via `meetings-tsml?area=Ohio`.
- Kent `ca-75af35f3d1db`: `36` records / `2` pages via filtered `district=kent` JSON feed.
- Florida `ca-6d96eea96ed1`: `28` records / `6` pages.
- Arkansas `ca-978cdf62a16a`: `16` records / `6` pages.
- Colorado `ca-612a2af62208`: `46` records / `6` pages.
- Norway `ca-4a2c9ec70003`: `6` records / `1` page.
- Thailand `ca-d57287ec55b9`: `13` records / `1` page.
- Minnesota `ca-8f845cc302e6`: `2` records / `1` page.
- New York `ca-e53b161d1e98`: `38` records / `2` pages.
- Connecticut `ca-041da33d75c7`: still `0` records; this matches the no-meetings landing-page notice.

Nebraska/Utah scope note:

- Nebraska `ca-a27a5c3933d7` is now `15` records / `1` page from `meetings-tsml?area=Nebraska`; prior `40`-record runs included `ca-online.org`.
- Utah `ca-6e8cc57bd9cf` is now `18` records / `1` page from `meetings-tsml?area=Utah`; the older `44`-record selective run included a broader external online listing, while the earlier fast run had `19` records on the Utah source itself.

## 2026-05-23 Import

The final dry-run artifact set `scrape_artifacts/ca-wide-dry-run-20260522-final-fast` was imported into the local development database `recovery_meeting_ingestion_dev`.

Dry-run gate:

- Command: `.venv/bin/python -m app.cli import-artifacts scrape_artifacts/ca-wide-dry-run-20260522-final-fast --dry-run`
- Summaries imported by default: `97` successful source summaries. The `3` failed source summaries were excluded.
- Records extracted: `2,356`.
- Records fetched: `2,341`.
- Candidates normalized: `2,340`.
- Review flags: `2,042`.

Real import:

- Command: `.venv/bin/python -m app.cli import-artifacts scrape_artifacts/ca-wide-dry-run-20260522-final-fast --no-dry-run`
- Raw records stored: `2,324`.
- Canonical meetings upserted: `2,340`.
- Post-import database counts: `2,159` sources, `5,939` raw meetings, `5,938` canonical meetings, `2,448` review flags, `255` import runs.
- `python -m app.cli report` returned `5,938` active meetings and `2,074` review flags.

Snapshot export:

- Dry run returned `5,135` snapshot meetings and `6` blocked-by-review records.
- Export command: `.venv/bin/python -m app.cli export-snapshot --no-dry-run`
- Output: `snapshots/meetings-2026-05-23T214837Z.json` and `snapshots/latest.json`.
- Snapshot DB row: `320bfded-333e-43da-b0f9-a377dfb61aa2`, `5,135` meetings, `6` blocked by review.

## 2026-05-23 Timezone Replay

The first artifact import left `1,134` open `missing_timezone` warnings because artifact replay normalized records before it had access to persisted source timezone metadata. Artifact replay now merges read-only source metadata from the local repository before normalization and uses the shared source timezone inference helper for single-timezone countries such as Ireland and the United Kingdom.

Validation:

- `.venv/bin/ruff check app tests`: passed.
- `.venv/bin/mypy app`: passed.
- `.venv/bin/pytest -q`: `101 passed, 10 skipped`.

Dry-run replay:

- Command: `.venv/bin/python -m app.cli import-artifacts scrape_artifacts/ca-wide-dry-run-20260522-final-fast --dry-run`
- Records extracted: `2,356`.
- Records fetched: `2,341`.
- Candidates normalized: `2,340`.
- Review flags: `1,106`, down from `2,042` on the first dry-run import gate.

Real replay:

- Command: `.venv/bin/python -m app.cli import-artifacts scrape_artifacts/ca-wide-dry-run-20260522-final-fast --no-dry-run`
- Raw records stored: `0`, because the same raw record hashes had already been imported.
- Canonical meetings upserted: `2,340`.
- Open review flags after replay: `1,133`, down from `2,074`.
- Open `missing_timezone` warnings after replay: `198` across `23` sources, down from `1,134` across `53` sources.
- Remaining open error flags: `1`, the Poland normalization failure `ca-18329a6abe7c` / `8de0df45026737b9`.

Replacement snapshot:

- Export command: `.venv/bin/python -m app.cli export-snapshot --no-dry-run`
- Output: `snapshots/meetings-2026-05-23T215857Z.json` and `snapshots/latest.json`.
- Snapshot DB row: `49923b3e-4607-440f-bd4c-b00dde39baef`, `5,135` meetings, `1` blocked by review.

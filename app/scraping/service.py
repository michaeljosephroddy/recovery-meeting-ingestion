from pathlib import Path

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.config import Settings
from app.ingest import IngestResult, adapter_for_source
from app.review.flags import ReviewFlag, flags_for_candidate
from app.scraping.bmlt_hints import bmlt_endpoint_from_html
from app.scraping.browser_crawler import BrowserCrawler
from app.scraping.models import CrawlSettings, ScrapeSourceResult
from app.scraping.raw_records import raw_records_from_extracted
from app.scraping.scoring import review_code_for_confidence
from app.sources.registry import AdapterType, Source, SourceType


class ScrapeResult:
    def __init__(
        self,
        *,
        scrape: ScrapeSourceResult,
        ingest: IngestResult,
    ) -> None:
        self.scrape = scrape
        self.ingest = ingest


async def scrape_source(
    source: Source,
    settings: Settings,
    *,
    crawl_settings: CrawlSettings | None = None,
    artifact_dir: Path | None = None,
) -> ScrapeResult:
    crawler = BrowserCrawler(
        source,
        user_agent=settings.user_agent,
        settings=crawl_settings or CrawlSettings(),
        artifact_dir=artifact_dir,
    )
    scrape = await crawler.crawl()
    raw_records = [
        record
        for page in scrape.pages
        for record in raw_records_from_extracted(source, page.extracted)
    ]
    raw_records = _dedupe_raw_records(raw_records)
    adapter_source = _browser_adapter_source(source)
    if not raw_records:
        bmlt_endpoint = _bmlt_endpoint_from_scrape(scrape)
        if bmlt_endpoint is not None:
            adapter_source = source.model_copy(
                update={
                    "source_type": SourceType.MEETING_FEED,
                    "adapter_type": AdapterType.BMLT,
                    "config": {
                        **source.config,
                        "bmlt_search_endpoint": bmlt_endpoint,
                        "scrape": {
                            "fallback": "bmlt",
                            "discovered_endpoint": bmlt_endpoint,
                        },
                    },
                }
            )
            adapter = adapter_for_source(adapter_source, settings)
            raw_records = await adapter.fetch()
        else:
            return ScrapeResult(
                scrape=scrape,
                ingest=IngestResult(raw_records=[], candidates=[], review_flags=[]),
            )
    else:
        adapter = adapter_for_source(adapter_source, settings)
    candidates = []
    review_flags: list[ReviewFlag] = []
    for raw in raw_records:
        extraction = raw.payload.get("extraction")
        confidence = _confidence_from_extraction(extraction)
        if confidence is not None:
            code = review_code_for_confidence(confidence)
            if code is not None:
                review_flags.append(
                    ReviewFlag(
                        code=code,
                        severity="error" if confidence < 0.45 else "warning",
                        message=f"scraped record confidence is {confidence:.2f}",
                        source_record_id=raw.source_record_id,
                    )
                )
            if confidence < 0.45:
                continue
        try:
            candidate = adapter.normalize(raw)
        except (AdapterPayloadError, ValueError) as exc:
            review_flags.append(
                ReviewFlag(
                    code="scrape_normalization_failed",
                    severity="error",
                    message=f"scraped record could not be normalized: {exc}",
                    source_record_id=raw.source_record_id,
                )
            )
            continue
        candidates.append(candidate)
        review_flags.extend(flags_for_candidate(candidate))
    return ScrapeResult(
        scrape=scrape,
        ingest=IngestResult(
            raw_records=raw_records,
            candidates=candidates,
            review_flags=review_flags,
        ),
    )


def _confidence_from_extraction(extraction: object) -> float | None:
    if not isinstance(extraction, dict) or extraction.get("confidence") is None:
        return None
    try:
        return float(extraction["confidence"])
    except (TypeError, ValueError):
        return None


def _browser_adapter_source(source: Source) -> Source:
    if source.adapter_type == AdapterType.PLAYWRIGHT_BROWSER:
        return source
    return source.model_copy(update={"adapter_type": AdapterType.PLAYWRIGHT_BROWSER})


def _dedupe_raw_records(raw_records: list[RawMeeting]) -> list[RawMeeting]:
    deduped: list[RawMeeting] = []
    seen: set[str] = set()
    for record in raw_records:
        if record.source_record_id in seen:
            continue
        seen.add(record.source_record_id)
        deduped.append(record)
    return deduped


def _bmlt_endpoint_from_scrape(scrape: ScrapeSourceResult) -> str | None:
    for page in scrape.pages:
        endpoint = bmlt_endpoint_from_html(page.html)
        if endpoint is not None:
            return endpoint
    return None

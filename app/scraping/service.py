from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.config import Settings
from app.ingest import IngestResult, adapter_for_source
from app.review.flags import ReviewFlag, flags_for_candidate
from app.scraping.bmlt_hints import bmlt_endpoint_from_html
from app.scraping.browser_crawler import BrowserCrawler
from app.scraping.models import CrawlSettings, ExtractedMeeting, ScrapedPage, ScrapeSourceResult
from app.scraping.na_brazil import fetch_na_brazil_cade_o_grupo_records
from app.scraping.na_direct_bmlt import fetch_direct_bmlt_records
from app.scraping.na_redriver import fetch_redriver_records
from app.scraping.na_source_specific import fetch_source_specific_na_records
from app.scraping.na_ukraine import fetch_ukraine_foreign_group_records
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
    direct_bmlt = await fetch_direct_bmlt_records(source, settings)
    if direct_bmlt is not None:
        adapter_source, bmlt_raw_records = direct_bmlt
        return _ingest_direct_raw_records(adapter_source, settings, bmlt_raw_records)

    brazil_raw_records = await fetch_na_brazil_cade_o_grupo_records(
        source,
        user_agent=settings.user_agent,
    )
    if brazil_raw_records is not None:
        return _ingest_direct_raw_records(source, settings, brazil_raw_records)

    redriver_raw_records = await fetch_redriver_records(
        source,
        user_agent=settings.user_agent,
    )
    if redriver_raw_records is not None:
        return _ingest_direct_raw_records(source, settings, redriver_raw_records)

    ukraine_raw_records = await fetch_ukraine_foreign_group_records(
        source,
        user_agent=settings.user_agent,
    )
    if ukraine_raw_records is not None:
        return _ingest_direct_raw_records(source, settings, ukraine_raw_records)

    source_specific_na_records = await fetch_source_specific_na_records(
        source,
        user_agent=settings.user_agent,
    )
    if source_specific_na_records is not None:
        return _ingest_direct_raw_records(source, settings, source_specific_na_records)

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
    if _scraped_result_too_broad_for_source(source, raw_records):
        return _broad_area_result(scrape)
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
            if _bmlt_fallback_too_broad_for_source(source, raw_records):
                return _broad_area_result(scrape)
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


def _ingest_direct_raw_records(
    source: Source,
    settings: Settings,
    raw_records: list[RawMeeting],
) -> ScrapeResult:
    adapter_source = (
        source if source.adapter_type == AdapterType.BMLT else _browser_adapter_source(source)
    )
    adapter = adapter_for_source(adapter_source, settings)
    candidates = []
    review_flags: list[ReviewFlag] = []
    for raw in raw_records:
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
        scrape=ScrapeSourceResult(
            source_id=source.id,
            source_url=source.url,
            status="succeeded",
            pages=[
                ScrapedPage(
                    url=source.url,
                    final_url=source.url,
                    title="NA Brazil cade-o-grupo AJAX",
                    html="",
                    extracted=_extracted_from_direct_raw_records(raw_records),
                )
            ],
        ),
        ingest=IngestResult(
            raw_records=raw_records,
            candidates=candidates,
            review_flags=review_flags,
        ),
    )


def _extracted_from_direct_raw_records(raw_records: list[RawMeeting]) -> list[ExtractedMeeting]:
    extracted = []
    for raw in raw_records:
        payload = dict(raw.payload)
        metadata = payload.pop("extraction", {})
        confidence = _confidence_from_extraction(metadata) or 0.95
        method = (
            str(metadata.get("method"))
            if isinstance(metadata, dict) and metadata.get("method")
            else "direct_source_adapter"
        )
        extracted.append(
            ExtractedMeeting(
                payload=payload,
                method=method,
                confidence=confidence,
                source_page_url=raw.source_url,
            )
        )
    return extracted


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


def _scraped_result_too_broad_for_source(source: Source, raw_records: list[RawMeeting]) -> bool:
    if source.fellowship != "na" or _source_na_type(source) != "area":
        return False
    if len(raw_records) >= 500:
        return True
    return len(raw_records) >= 200 and _records_from_current_meeting_list(raw_records)


def _records_from_current_meeting_list(raw_records: list[RawMeeting]) -> bool:
    for record in raw_records:
        extraction = record.payload.get("extraction")
        if not isinstance(extraction, dict):
            continue
        source_page_url = extraction.get("source_page_url")
        if not isinstance(source_page_url, str):
            continue
        query_keys = {
            key.lower()
            for key, _value in parse_qsl(
                urlparse(source_page_url).query,
                keep_blank_values=True,
            )
        }
        if "current-meeting-list" in query_keys:
            return True
    return False


def _bmlt_fallback_too_broad_for_source(source: Source, raw_records: list[RawMeeting]) -> bool:
    if source.fellowship != "na" or _source_na_type(source) != "area":
        return False
    if len(raw_records) < 100:
        return False
    service_bodies = {
        str(record.payload.get("service_body_bigint") or record.payload.get("service_body_name"))
        for record in raw_records
        if record.payload.get("service_body_bigint") or record.payload.get("service_body_name")
    }
    return len(service_bodies) >= 3


def _broad_area_result(scrape: ScrapeSourceResult) -> ScrapeResult:
    return ScrapeResult(
        scrape=scrape,
        ingest=IngestResult(
            raw_records=[],
            candidates=[],
            review_flags=[
                ReviewFlag(
                    code="scrape_broad_area_result",
                    severity="warning",
                    message=(
                        "scrape returned a broad regional result set for an area source; "
                        "rows were not imported"
                    ),
                )
            ],
        ),
    )


def _source_na_type(source: Source) -> str | None:
    metadata = source.config.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("na_type")
    if not isinstance(value, str):
        return None
    return value.strip().casefold() or None


def _bmlt_endpoint_from_scrape(scrape: ScrapeSourceResult) -> str | None:
    for page in scrape.pages:
        endpoint = bmlt_endpoint_from_html(page.html)
        if endpoint is not None:
            return endpoint
    return None

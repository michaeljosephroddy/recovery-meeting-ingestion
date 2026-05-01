from app.config import Settings
from app.scraping.models import ExtractedMeeting, ScrapedPage, ScrapeSourceResult
from app.scraping.service import scrape_source
from app.sources.registry import AdapterType, Source, SourceType


async def test_scrape_source_returns_empty_ingest_for_empty_unknown_source(monkeypatch) -> None:
    async def fake_crawl(self) -> ScrapeSourceResult:  # noqa: ANN001
        return ScrapeSourceResult(
            source_id=self.source.id,
            source_url=self.source.url,
            status="succeeded",
            pages=[
                ScrapedPage(
                    url=self.source.url,
                    final_url=self.source.url,
                    title="No meetings",
                    html="<html><h1>No meetings here</h1></html>",
                )
            ],
        )

    monkeypatch.setattr("app.scraping.browser_crawler.BrowserCrawler.crawl", fake_crawl)
    source = Source(
        id="ca-empty",
        fellowship="ca",
        name="Empty Source",
        url="https://example.org/",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.UNKNOWN,
    )

    result = await scrape_source(source, Settings())

    assert result.scrape.status == "succeeded"
    assert result.ingest.raw_records == []
    assert result.ingest.candidates == []
    assert result.ingest.review_flags == []


async def test_scrape_source_dedupes_same_meeting_across_pages(monkeypatch) -> None:
    meeting = ExtractedMeeting(
        payload={
            "name": "Monday Main",
            "day": "Monday",
            "time": "7:30 pm",
            "address_line1": "10 Main Street",
        },
        method="heuristic_table_row",
        confidence=0.9,
        source_page_url="https://example.org/",
    )

    async def fake_crawl(self) -> ScrapeSourceResult:  # noqa: ANN001
        return ScrapeSourceResult(
            source_id=self.source.id,
            source_url=self.source.url,
            status="succeeded",
            pages=[
                ScrapedPage(
                    url=self.source.url,
                    final_url=self.source.url,
                    title="Home",
                    html="<html></html>",
                    extracted=[meeting],
                ),
                ScrapedPage(
                    url=f"{self.source.url}meetings",
                    final_url=f"{self.source.url}meetings",
                    title="Meetings",
                    html="<html></html>",
                    extracted=[meeting],
                ),
            ],
        )

    monkeypatch.setattr("app.scraping.browser_crawler.BrowserCrawler.crawl", fake_crawl)
    source = Source(
        id="ca-duplicate",
        fellowship="ca",
        name="Duplicate Source",
        url="https://example.org/",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.UNKNOWN,
        config={"timezone": "UTC"},
    )

    result = await scrape_source(source, Settings())

    assert len(result.ingest.raw_records) == 1
    assert len(result.ingest.candidates) == 1

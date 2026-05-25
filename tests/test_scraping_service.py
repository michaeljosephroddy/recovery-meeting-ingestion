from app.adapters.base import RawMeeting
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


async def test_scrape_source_rejects_broad_bmlt_fallback_for_na_area(monkeypatch) -> None:
    async def fake_crawl(self) -> ScrapeSourceResult:  # noqa: ANN001
        return ScrapeSourceResult(
            source_id=self.source.id,
            source_url=self.source.url,
            status="succeeded",
            pages=[
                ScrapedPage(
                    url=self.source.url,
                    final_url=self.source.url,
                    title="Meetings",
                    html="""
                    <script>
                    crouton = new Crouton({
                      "root_server": "https:\\/\\/bmlt.example.org\\/main_server",
                      "service_body": [631],
                      "recurse_service_bodies": true
                    });
                    </script>
                    """,
                )
            ],
        )

    class FakeAdapter:
        async def fetch(self) -> list[RawMeeting]:
            return [
                RawMeeting(
                    source_id="na-area",
                    source_record_id=str(index),
                    source_url="https://example.org/area",
                    content_hash=str(index),
                    payload={
                        "id_bigint": str(index),
                        "service_body_bigint": str(index % 4),
                    },
                )
                for index in range(120)
            ]

        def normalize(self, raw: RawMeeting):  # noqa: ANN001
            raise AssertionError("broad fallback rows should not be normalized")

    monkeypatch.setattr("app.scraping.browser_crawler.BrowserCrawler.crawl", fake_crawl)
    monkeypatch.setattr("app.scraping.service.adapter_for_source", lambda *_: FakeAdapter())
    source = Source(
        id="na-area",
        fellowship="na",
        name="Small Area",
        url="https://example.org/area",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
        config={"metadata": {"na_type": "area"}},
    )

    result = await scrape_source(source, Settings())

    assert result.ingest.raw_records == []
    assert result.ingest.candidates == []
    assert [flag.code for flag in result.ingest.review_flags] == [
        "scrape_broad_area_result"
    ]


async def test_scrape_source_allows_large_single_body_bmlt_fallback(monkeypatch) -> None:
    async def fake_crawl(self) -> ScrapeSourceResult:  # noqa: ANN001
        return ScrapeSourceResult(
            source_id=self.source.id,
            source_url=self.source.url,
            status="succeeded",
            pages=[
                ScrapedPage(
                    url=self.source.url,
                    final_url=self.source.url,
                    title="Meetings",
                    html="""
                    <script>
                    crouton = new Crouton({
                      "root_server": "https:\\/\\/bmlt.example.org\\/main_server",
                      "service_body": [12]
                    });
                    </script>
                    """,
                )
            ],
        )

    class FakeAdapter:
        async def fetch(self) -> list[RawMeeting]:
            return [
                RawMeeting(
                    source_id="na-area",
                    source_record_id=str(index),
                    source_url="https://example.org/area",
                    content_hash=str(index),
                    payload={
                        "id_bigint": str(index),
                        "service_body_bigint": "12",
                    },
                )
                for index in range(120)
            ]

        def normalize(self, raw: RawMeeting):  # noqa: ANN001
            raise ValueError("fixture stops after broad-scope guard")

    monkeypatch.setattr("app.scraping.browser_crawler.BrowserCrawler.crawl", fake_crawl)
    monkeypatch.setattr("app.scraping.service.adapter_for_source", lambda *_: FakeAdapter())
    source = Source(
        id="na-area",
        fellowship="na",
        name="Single Body Area",
        url="https://example.org/area",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
        config={"metadata": {"na_type": "area"}},
    )

    result = await scrape_source(source, Settings())

    assert len(result.ingest.raw_records) == 120
    assert {
        flag.code for flag in result.ingest.review_flags
    } == {"scrape_normalization_failed"}


async def test_scrape_source_uses_na_brazil_direct_records(monkeypatch) -> None:
    raw = RawMeeting(
        source_id="na-brazil",
        source_record_id="copy0-domingo-20:00-0",
        source_url="https://www.na.org.br/grupos",
        content_hash="abc",
        payload={
            "source_record_id": "copy0-domingo-20:00-0",
            "name": "Grupo 12 Passos",
            "day": "domingo",
            "time": "20:00",
            "address_line1": "Praça da Bandeira S/N",
            "city": "Presidente Prudente",
            "region": "São Paulo",
            "country": "Brazil",
            "timezone": "America/Sao_Paulo",
        },
    )

    async def fake_fetch(source, *, user_agent):  # noqa: ANN001
        return [raw]

    async def fail_crawl(self):  # noqa: ANN001
        raise AssertionError("direct Brazil scraper should bypass browser crawl")

    monkeypatch.setattr("app.scraping.service.fetch_na_brazil_cade_o_grupo_records", fake_fetch)
    monkeypatch.setattr("app.scraping.browser_crawler.BrowserCrawler.crawl", fail_crawl)
    source = Source(
        id="na-brazil",
        fellowship="na",
        name="Brazil Region",
        url="https://www.na.org.br/grupos",
        country="Brazil",
        region="Sao Paulo",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
    )

    result = await scrape_source(source, Settings())

    assert len(result.ingest.raw_records) == 1
    assert len(result.ingest.candidates) == 1
    assert result.ingest.candidates[0].name == "Grupo 12 Passos"


async def test_scrape_source_uses_direct_bmlt_records(monkeypatch) -> None:
    raw = RawMeeting(
        source_id="na-direct",
        source_record_id="123",
        source_url="https://example.org/main_server",
        content_hash="abc",
        payload={
            "id_bigint": "123",
            "meeting_name": "Direct BMLT",
            "weekday_tinyint": "2",
            "start_time": "19:00:00",
            "formatted_address": "726 South Salisbury Boulevard",
            "location_municipality": "Salisbury",
            "location_province": "Maryland",
            "location_nation": "United States",
        },
    )
    adapter_source = Source(
        id="na-direct",
        fellowship="na",
        name="Direct",
        url="https://example.org/main_server",
        country="United States",
        region="Maryland",
        source_type=SourceType.MEETING_FEED,
        adapter_type=AdapterType.BMLT,
    )

    async def fake_fetch(source, settings):  # noqa: ANN001
        return adapter_source, [raw]

    async def fail_crawl(self):  # noqa: ANN001
        raise AssertionError("direct BMLT should bypass browser crawl")

    monkeypatch.setattr("app.scraping.service.fetch_direct_bmlt_records", fake_fetch)
    monkeypatch.setattr("app.scraping.browser_crawler.BrowserCrawler.crawl", fail_crawl)
    source = Source(
        id="na-direct",
        fellowship="na",
        name="Direct",
        url="https://example.org/",
        country="United States",
        region="Maryland",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
    )

    result = await scrape_source(source, Settings())

    assert len(result.ingest.raw_records) == 1
    assert len(result.ingest.candidates) == 1
    assert result.ingest.candidates[0].name == "Direct BMLT"


async def test_scrape_source_rejects_large_rendered_result_for_na_area(monkeypatch) -> None:
    meetings = [
        ExtractedMeeting(
            payload={
                "name": f"Meeting {index}",
                "day": "Monday",
                "time": "7:30 pm",
                "address_line1": "10 Main Street",
            },
            method="heuristic_table_row",
            confidence=0.9,
            source_page_url="https://example.org/all-meetings/",
        )
        for index in range(500)
    ]

    async def fake_crawl(self) -> ScrapeSourceResult:  # noqa: ANN001
        return ScrapeSourceResult(
            source_id=self.source.id,
            source_url=self.source.url,
            status="succeeded",
            pages=[
                ScrapedPage(
                    url=self.source.url,
                    final_url=self.source.url,
                    title="All Meetings",
                    html="<html></html>",
                    extracted=meetings,
                )
            ],
        )

    monkeypatch.setattr("app.scraping.browser_crawler.BrowserCrawler.crawl", fake_crawl)
    source = Source(
        id="na-area",
        fellowship="na",
        name="Small Area",
        url="https://example.org/area",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
        config={"metadata": {"na_type": "area"}},
    )

    result = await scrape_source(source, Settings())

    assert result.ingest.raw_records == []
    assert result.ingest.candidates == []
    assert [flag.code for flag in result.ingest.review_flags] == [
        "scrape_broad_area_result"
    ]

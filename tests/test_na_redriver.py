from app.adapters.static_html import StaticHtmlAdapter
from app.scraping.na_redriver import _meeting_pdf_url, _raw_records_from_schedule
from app.sources.registry import AdapterType, Source, SourceType


def test_redriver_meetings_page_finds_schedule_pdf() -> None:
    html = """
    <html><body>
      <a href="/_files/ugd/schedule.pdf">OklaTex Area Meeting Schedule PDF</a>
    </body></html>
    """

    assert _meeting_pdf_url(html) == "https://www.redriverna.com/_files/ugd/schedule.pdf"


def test_redriver_schedule_records_are_split_by_source_region() -> None:
    source = Source(
        id="na-a9fe8b207548",
        fellowship="na",
        name="Red River Region",
        url="https://redriverna.org/meetings/nearest",
        country="United States",
        region="Texas",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
    )

    records = _raw_records_from_schedule(source, "https://www.redriverna.com/schedule.pdf")

    assert len(records) == 29
    assert {record.payload["region"] for record in records} == {"Texas"}
    candidate = StaticHtmlAdapter(source).normalize(records[0])
    assert candidate.occurrences[0].timezone == "America/Chicago"
    assert candidate.address_line1 == "301 W. Maple"
    assert candidate.occurrences[0].start_time_local is not None

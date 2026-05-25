from app.adapters.static_html import StaticHtmlAdapter
from app.scraping.na_source_specific import (
    raw_records_from_belarus_html,
    raw_records_from_bermuda_html,
    raw_records_from_ct_bmltwf_payload,
    raw_records_from_luzon_html,
    raw_records_from_nrvana_html,
    raw_records_from_thailand_html,
)
from app.sources.registry import AdapterType, Source, SourceType


def source(source_id: str, url: str, country: str = "United States") -> Source:
    return Source(
        id=source_id,
        fellowship="na",
        name="NA Source",
        url=url,
        country=country,
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
    )


def test_ct_bmltwf_payload_filters_unpublished_and_maps_rows() -> None:
    src = source("na-40333db921fd", "https://ctna.org/find-a-meeting/")
    payload = {
        "message": """
        [
          {"id": 1, "published": false, "day": 1, "startTime": "19:30", "name": "Old"},
          {
            "id": 2, "published": true, "day": 3, "startTime": "19:30",
            "name": "Miracles", "location_text": "Church",
            "location_street": "138 Candlewood Lake Road",
            "location_municipality": "Brookfield", "location_province": "CT",
            "virtual_meeting_link": "https://zoom.us/j/6143364882"
          }
        ]
        """,
    }

    records = raw_records_from_ct_bmltwf_payload(src, payload)

    assert len(records) == 1
    candidate = StaticHtmlAdapter(src).normalize(records[0])
    assert candidate.name == "Miracles"
    assert candidate.occurrences[0].day_of_week == 3
    assert candidate.meeting_type == "hybrid"


def test_nrvana_stacked_schedule_extracts_meeting_blocks() -> None:
    src = source("na-d29507d2e6d6", "https://nrvana.org/meetings")
    html = """
    <main>Meetings
    Monday
    HOW Group
    7pm
    Highland Park Community Church
    6144 Wright Ave.
    Dublin, Va 24084
    ( o, d, hc )
    Tuesday
    KISS Group
    7pm
    St Thomas Episcopal Church
    103 E. Main st.
    Christiansburg VA
    (o , v , hc)
    Meeting Key:</main>
    """

    records = raw_records_from_nrvana_html(src, html)

    assert len(records) == 2
    first = StaticHtmlAdapter(src).normalize(records[0])
    assert first.name == "HOW Group"
    assert first.city == "Dublin"
    assert first.occurrences[0].start_time_local is not None


def test_luzon_weebly_schedule_extracts_time_first_blocks() -> None:
    src = source("na-741664cfd8df", "https://luzonna.weebly.com/na-meetings.html", "Philippines")
    html = """
    <div>NA MEETINGS IN LUZON AREA</div>
    <div>Mondays</div>
    <div>6:30 PM Quezon City, Manila</div>
    <div>(Open)</div>
    <div>“Buhay Ka Pa” Group</div>
    <div>55A, 11th Street, New Manila, QC</div>
    <div>Contact: Fernan +63 922 8841439</div>
    <div>Note:</div>
    """

    records = raw_records_from_luzon_html(src, html)

    assert len(records) == 1
    assert records[0].payload["city"] == "Quezon City, Manila"
    assert "Buhay Ka Pa" in records[0].payload["name"]


def test_bermuda_wordpress_schedule_extracts_hybrid_details() -> None:
    src = source("na-318bd9c44950", "https://www.nabermuda.org", "Bermuda")
    html = """
    <main>B.I.A.N.A Meetings Schedule
    MONDAY
    Journey Group (Open)
    Location (hybrid):
    Pathways, 61 Verdmont Road, Smiths
    Zoom ID: 853 0788 7299
    Zoom Password: 600660
    7 - 8:30pm (AST)
    World Committee Code: G00218574
    TUESDAY
    Request</main>
    """

    records = raw_records_from_bermuda_html(src, html)

    assert len(records) == 1
    candidate = StaticHtmlAdapter(src).normalize(records[0])
    assert candidate.name == "Journey Group"
    assert candidate.meeting_type == "hybrid"
    assert candidate.occurrences[0].timezone == "Atlantic/Bermuda"


def test_thailand_area_page_extracts_labelled_blocks() -> None:
    src = source("na-d4eceee5b4d4", "https://na-thailand.org/meetings/", "Thailand")
    html = """
    <main>Bangkok Area Meetings
    Monday - 7:30pm (19.30)
    Name:
    BNH Hospital
    Address:
    BNH Hospital Convent Road, Sathorn
    Format:
    Just for Today Reading / Open
    See Map
    Need to add a new meeting?</main>
    """

    records = raw_records_from_thailand_html(
        src,
        html,
        "https://na-thailand.org/meetings/bangkok-meetings/",
    )

    assert len(records) == 1
    assert records[0].payload["city"] == "Bangkok"
    assert records[0].payload["time"] == "19:30"


def test_belarus_schedule_tables_extract_russian_rows() -> None:
    src = source("na-494e4e542045", "https://na-rb.by", "Belarus")
    html = """
    <p class="h3">Группа «ДЖОКЕР»</p>
    <table><tr><td>г. Борисов, ул 50 лет БССР д.27а помещение ТЦСОН</td></tr></table>
    <table>
      <tr><td>РАСПИСАНИЕ</td></tr>
      <tr><td>Понедельник</td><td>19:00-20:00</td><td>Жить чистыми</td></tr>
      <tr><td>20:00-21:10</td><td>Рабочее собрание Первая пятница месяца</td></tr>
    </table>
    """

    records = raw_records_from_belarus_html(src, html, "https://na-rb.by/groups/minsk-reg/borisov/")

    assert len(records) == 1
    candidate = StaticHtmlAdapter(src).normalize(records[0])
    assert candidate.name == "ДЖОКЕР"
    assert candidate.city == "Борисов"
    assert candidate.occurrences[0].day_of_week == 1

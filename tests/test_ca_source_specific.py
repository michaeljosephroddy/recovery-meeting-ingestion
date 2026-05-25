from app.adapters.static_html import StaticHtmlAdapter
from app.scraping.ca_source_specific import (
    raw_records_from_denmark_html,
    raw_records_from_maritimes_html,
    raw_records_from_nashville_html,
    raw_records_from_quebec_html,
    raw_records_from_texas_html,
)
from app.sources.registry import AdapterType, Source, SourceType


def source(source_id: str, url: str, country: str = "United States") -> Source:
    return Source(
        id=source_id,
        fellowship="ca",
        name="CA Source",
        url=url,
        country=country,
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
    )


def test_denmark_table_parser_maps_rows() -> None:
    src = source("ca-63a0c6bbe7d2", "https://ca-danmark.dk/moeder/", "Denmark")
    html = """
    <table>
      <tr><th>Dag</th><th>Møde</th><th>Tid</th><th>Sted</th><th>Link</th></tr>
      <tr><td>Mandag</td><td>“Trin+Speaker Møde” Dørene åbner kl 18:00</td>
      <td>19:00-20:15</td><td>Julius Andersens Vej 3, 2450 København SV</td><td>Se på kort</td></tr>
    </table>
    """

    records = raw_records_from_denmark_html(src, html, src.url)

    assert len(records) == 1
    candidate = StaticHtmlAdapter(src).normalize(records[0])
    assert candidate.name == "Trin+Speaker Møde"
    assert candidate.occurrences[0].day_of_week == 1
    assert str(candidate.occurrences[0].start_time_local) == "19:00:00"


def test_quebec_tables_use_table_order_for_days() -> None:
    src = source("ca-f60993c27baf", "https://www.caquebec.org/reunions/", "Canada")
    html = """
    <table>
      <tr><td>10:30</td><td>LE DÉGEL</td></tr>
      <tr><td>C/P/O</td><td>5075A rue Rivard</td></tr>
      <tr><td></td><td>Montréal, H2J 2P2</td></tr>
    </table>
    """

    records = raw_records_from_quebec_html(src, html, src.url)

    assert len(records) == 1
    candidate = StaticHtmlAdapter(src).normalize(records[0])
    assert candidate.name == "LE DÉGEL"
    assert candidate.occurrences[0].day_of_week == 0
    assert candidate.region == "Quebec"


def test_maritimes_online_cards_extract_zoom_meetings() -> None:
    src = source("ca-4b3b7087b949", "https://ca-maritimes.org/", "Canada")
    html = """
    <main>
      <h2>Zoom Meetings</h2>
      <p>Great Expectations</p><p>Sundays at 8pm</p>
      <a href="https://us02web.zoom.us/j/81525211712">Join Now</a>
    </main>
    """

    records = raw_records_from_maritimes_html(src, html, src.url)

    assert len(records) == 1
    candidate = StaticHtmlAdapter(src).normalize(records[0])
    assert candidate.name == "Great Expectations"
    assert candidate.meeting_type == "online"
    assert str(candidate.online_url) == "https://us02web.zoom.us/j/81525211712"


def test_nashville_name_before_time_blocks_extract_addresses() -> None:
    src = source("ca-200708853eaf", "https://canashville.com/")
    html = """
    <main>
      <p>MONDAY</p><p>Off The Rocks</p><p>TIME: 7:30 PM</p>
      <p>3511 Gallatin Pike</p><p>Nashville, TN 37216</p>
      <p>MONDAY</p><p>Jumping Off</p><p>TIME: 7:00 PM</p>
      <p>ZOOM MEETING</p><p>Meeting ID: 820 1059 3122</p>
    </main>
    """

    records = raw_records_from_nashville_html(src, html, src.url)

    assert len(records) == 2
    first = StaticHtmlAdapter(src).normalize(records[0])
    second = StaticHtmlAdapter(src).normalize(records[1])
    assert first.name == "Off The Rocks"
    assert first.meeting_type == "in_person"
    assert second.name == "Jumping Off"
    assert second.meeting_type == "online"


def test_texas_time_blocks_extract_multiple_meetings_per_day() -> None:
    src = source("ca-f6c1ff14a8cb", "https://www.ca-texas.org/")
    html = """
    <main>
      <p>MEETINGS IN THE GREATER HOUSTON AREA</p>
      <p>Sunday</p><p>10:00 am</p><p>Keep Hope Alive</p>
      <p>3815 Live Oak St, Houston, TX 77004</p>
      <p>12:00 pm</p><p>Overcomers Group</p>
      <p>465 W Parker Rd, Houston, TX 77091</p>
      <p>Other CA Meetings</p>
    </main>
    """

    records = raw_records_from_texas_html(src, html, src.url)

    assert len(records) == 2
    candidate = StaticHtmlAdapter(src).normalize(records[1])
    assert candidate.name == "Overcomers Group"
    assert candidate.occurrences[0].day_of_week == 0

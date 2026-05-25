from app.adapters.static_html import StaticHtmlAdapter
from app.scraping.na_ukraine import raw_records_from_ukraine_foreign_groups
from app.sources.registry import AdapterType, Source, SourceType


def test_ukraine_foreign_groups_extracts_wordpress_block_schedules() -> None:
    source = Source(
        id="na-be52cc6d882d",
        fellowship="na",
        name="Ukraine Region",
        url="https://ua.na-ua.org/zakordonni-ukrayinomovni-grupi",
        country="Ukraine",
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
    )
    html = """
    <div class="entry-content">
      <h2><strong>Канада, Альберта, Едмонтон</strong></h2>
      <ul>
        <li><strong>Жива група</strong></li>
        <li>15608 104 Avenue Northwest</li>
        <li>Щосереди о <strong>19:30</strong> (7:30 PM)</li>
      </ul>
      <h2><strong>Німеччина</strong></h2>
      <ul>
        <li><strong>Група «Вечорниці»</strong></li>
        <li>Franz-Mehring-Platz 1, 10243 <strong>Berlin</strong></li>
        <li>Понеділок <strong>18:00-19:30</strong></li>
        <li>Субота <strong>11:00-12:00</strong></li>
      </ul>
    </div>
    """

    records = raw_records_from_ukraine_foreign_groups(source, html)

    assert len(records) == 3
    canada = records[0].payload
    assert canada["day"] == "Wednesday"
    assert canada["time"] == "19:30"
    assert canada["country"] == "Canada"
    assert canada["region"] == "Alberta"
    assert canada["city"] == "Edmonton"
    assert canada["timezone"] == "America/Edmonton"

    candidate = StaticHtmlAdapter(source).normalize(records[1])
    assert candidate.name == "Вечорниці"
    assert candidate.country == "Germany"
    assert candidate.occurrences[0].day_of_week == 1
    assert candidate.occurrences[0].end_time_local is not None

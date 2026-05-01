from app.scraping.browser_crawler import is_allowed_url, prioritize_links
from app.scraping.evidence import read_scrape_summary, write_scrape_evidence
from app.scraping.extract_meetings import extract_meetings_from_html
from app.scraping.meeting_page_detector import score_html, score_link
from app.scraping.models import BrowserActionTrace, ScrapedPage, ScrapeSourceResult
from app.scraping.scoring import review_code_for_confidence


def test_meeting_page_detector_scores_meeting_links_above_noise() -> None:
    meeting = score_link("https://example.org/find-a-meeting", "Find a meeting")
    donate = score_link("https://example.org/donate", "Donate now")

    assert meeting.score >= 0.5
    assert "url_or_text:find-a-meeting" in meeting.signals
    assert donate.score == 0
    assert "donate" in donate.negative_signals


def test_meeting_page_detector_scores_rendered_meeting_html() -> None:
    html = """
    <html>
      <title>Meetings</title>
      <h1>Find a meeting</h1>
      <table>
        <tr><th>Day</th><th>Time</th><th>Location</th></tr>
        <tr><td>Monday</td><td>7:30 pm</td><td>10 Main Street</td></tr>
      </table>
    </html>
    """

    score = score_html("https://example.org/meetings", html)

    assert score.score >= 0.75
    assert "meeting_table" in score.signals
    assert "day_and_time_text" in score.signals


def test_extract_meetings_uses_configured_selectors_first() -> None:
    html = """
    <div class="meeting" data-id="m1">
      <span class="name">Monday Main</span>
      <span class="day">Monday</span>
      <span class="time">7:30 pm</span>
      <span class="address">10 Main Street</span>
    </div>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings",
        source_config={
            "selectors": {
                "row": ".meeting",
                "source_record_id": ".meeting::attr(data-id)",
                "name": ".name",
                "day": ".day",
                "time": ".time",
                "address_line1": ".address",
            }
        },
    )

    assert len(meetings) == 1
    assert meetings[0].method == "configured_selectors"
    assert meetings[0].confidence >= 0.78
    assert meetings[0].payload_with_metadata()["extraction"]["source_page_url"] == (
        "https://example.org/meetings"
    )


def test_extract_meetings_from_table_headers() -> None:
    html = """
    <table>
      <thead>
        <tr><th>Meeting</th><th>Day</th><th>Time</th><th>Address</th><th>Type</th></tr>
      </thead>
      <tbody>
        <tr>
          <td>Monday Main</td><td>Monday</td><td>7:30 pm</td>
          <td>10 Main Street</td><td>Open, Discussion</td>
        </tr>
      </tbody>
    </table>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings",
    )

    assert len(meetings) == 1
    assert meetings[0].method == "heuristic_table_row"
    assert meetings[0].payload["name"] == "Monday Main"
    assert meetings[0].payload["address_line1"] == "10 Main Street"
    assert meetings[0].confidence >= 0.75


def test_extract_meetings_from_table_time_with_day_and_platform() -> None:
    html = """
    <table>
      <tr><th>Time</th><th>Name</th><th>Address / Platform</th></tr>
      <tr><td>3:00 PM Friday</td><td>Serenity Now</td><td>Zoom</td></tr>
    </table>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/",
    )

    assert len(meetings) == 1
    assert meetings[0].payload["day"] == "Friday"
    assert meetings[0].payload["time"] == "3:00 PM"
    assert meetings[0].payload["phone_join_info"] == "Zoom"


def test_extract_meetings_from_rendered_bmlt_table() -> None:
    html = """
    <table class="bmlt-table">
      <tr class="bmlt-data-row" id="meeting-data-row-1788" data-formats="open">
        <td class="bmlt-column1">
          <div class="bmlt-day">Sunday</div>
          <div class="bmlt-time-2">6:00 pm - 7:30 pm</div>
        </td>
        <td class="bmlt-column2">
          <div class="meeting-name"><a href="#">We Together Hand in Hand</a></div>
          <div class="location-text">Redeemer Lutheran Church</div>
          <div class="meeting-address">10 Prospect St., Auburn, NY, 13021</div>
        </td>
        <td><div class="geo hide">42.944002,-76.53942</div></td>
      </tr>
    </table>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/find-a-meeting/",
    )

    assert len(meetings) == 1
    assert meetings[0].method == "bmlt_rendered_table_row"
    assert meetings[0].payload["source_record_id"] == "1788"
    assert meetings[0].payload["day"] == "Sunday"
    assert meetings[0].payload["time"] == "6:00 pm"
    assert meetings[0].payload["name"] == "We Together Hand in Hand"
    assert meetings[0].payload["venue_name"] == "Redeemer Lutheran Church"
    assert meetings[0].payload["address_line1"] == "10 Prospect St., Auburn, NY, 13021"


def test_extract_meetings_from_wordpress_day_sections() -> None:
    html = """
    <article>
      <div class="entry-content">
        <h3>Mondays</h3>
        <p>12:00 pm - S/D</p>
        <p>Birds of A Feather - Pigeon Coop</p>
        <p>4415 S. Rural Rd., Tempe, AZ 85282</p>
        <p>7:00 p.m. - Nothing To Withhold</p>
        <p>ONLINE Zoom Meeting</p>
        <p>Meeting ID: 852 9758 1348</p>
      </div>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings",
    )

    assert [meeting.method for meeting in meetings] == [
        "heuristic_day_section",
        "heuristic_day_section",
    ]
    assert meetings[0].payload["day"] == "Monday"
    assert meetings[0].payload["address_line1"] == "4415 S. Rural Rd., Tempe, AZ 85282"
    assert meetings[1].payload["phone_join_info"] == "ONLINE Zoom Meeting Meeting ID: 852 9758 1348"


def test_extract_meetings_from_repeated_cards() -> None:
    html = """
    <section>
      <article class="meeting-card">
        <h3>Tuesday Step</h3>
        <p>Tuesday 8:00 pm</p>
        <p class="address">22 River Road</p>
      </article>
      <article class="meeting-card">
        <h3>Friday Online</h3>
        <p>Friday 6:00 pm</p>
        <a href="https://zoom.example.org/friday">Join online</a>
      </article>
    </section>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings",
    )

    assert [meeting.payload["name"] for meeting in meetings] == ["Tuesday Step", "Friday Online"]
    assert {meeting.method for meeting in meetings} == {"heuristic_card"}
    assert meetings[1].payload["online_url"] == "https://zoom.example.org/friday"


def test_extract_meetings_from_site_builder_content_blocks() -> None:
    html = """
    <div data-ux="ContentBasic">
      <h4>Park Between the Lines - Oxford, MS</h4>
      <p>St. Andrews Methodist Church</p>
      <p>431 North 16th St Oxford, MS 38655</p>
      <ul><li><strong>Thursday 8:30pm</strong></li></ul>
    </div>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings",
    )

    assert len(meetings) == 1
    assert meetings[0].method == "heuristic_card"
    assert meetings[0].payload["name"] == "Park Between the Lines - Oxford, MS"
    assert meetings[0].payload["day"] == "Thursday"
    assert meetings[0].payload["time"] == "8:30pm"
    assert meetings[0].payload["address_line1"] == "431 North 16th St Oxford, MS 38655"


def test_text_fallback_rejects_generic_app_store_page_text() -> None:
    html = """
    <title>Meetings - Fellowship</title>
    <p>Monday 9:00 am</p>
    <p>A Twelve Step Fellowship of, by and for addicts seeking recovery.</p>
    <p>https://apps.apple.com/app/id6504262893</p>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings",
    )

    assert meetings == []


def test_card_extraction_rejects_event_links_without_location() -> None:
    html = """
    <article>
      <h3>Annual Speaker Meeting</h3>
      <p>Sunday 10am</p>
      <a href="https://example.org/event/speaker-meeting/">Read more</a>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings",
    )

    assert meetings == []


def test_confidence_threshold_review_codes() -> None:
    assert review_code_for_confidence(0.30) == "scrape_very_low_confidence"
    assert review_code_for_confidence(0.60) == "scrape_low_confidence"
    assert review_code_for_confidence(0.80) is None


def test_evidence_writer_round_trips_summary(tmp_path) -> None:
    page = ScrapedPage(
        url="https://example.org/",
        final_url="https://example.org/meetings",
        title="Meetings",
        html="<html><h1>Meetings</h1></html>",
        page_score=0.9,
        page_signals=["meeting_table"],
        actions=[BrowserActionTrace(action="click", selector="#list")],
        extracted=[],
    )
    result = ScrapeSourceResult(
        source_id="aa-example",
        source_url="https://example.org/",
        status="succeeded",
        pages=[page],
    )

    evidence_dir = write_scrape_evidence(result, tmp_path)
    summary = read_scrape_summary(evidence_dir)

    assert summary["source_id"] == "aa-example"
    assert summary["pages_visited"] == 1
    assert (evidence_dir / "pages").exists()


def test_crawler_prioritizes_meeting_links_and_stays_on_site() -> None:
    links = [
        {"url": "https://example.org/news", "text": "News"},
        {"url": "https://example.org/find-a-meeting", "text": "Find a meeting"},
        {"url": "https://social.example.net/page", "text": "Social"},
        {"url": "https://example.org/donate", "text": "Donate"},
    ]

    prioritized = prioritize_links("https://example.org/", links)

    assert [link["url"] for link in prioritized] == [
        "https://example.org/find-a-meeting",
        "https://example.org/news",
        "https://example.org/donate",
    ]
    assert is_allowed_url("https://example.org/", "https://meetings.example.org/list")
    assert not is_allowed_url("https://example.org/", "https://external.test/meetings")

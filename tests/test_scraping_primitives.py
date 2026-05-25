from collections import deque

from app.scraping.browser_crawler import (
    _extract_google_calendar_ics_meetings,
    _fetch_json_feed_text,
    _google_calendar_ics_urls,
    _has_deeper_meeting_directory_link,
    _has_pending_meeting_branch,
    _html_with_pdf_text,
    _looks_like_downloadable_meeting_list_url,
    _looks_like_not_found_page,
    _meeting_pdf_links,
    _page_links,
    _tsml_json_feed_url_from_html,
    _without_common_meeting_path_links,
    _wix_data_items_to_text,
    common_meeting_path_links,
    initial_crawl_queue,
    is_allowed_url,
    is_common_meeting_path,
    prioritize_links,
    remembered_meeting_page_urls,
    remembered_page_expected_records,
    should_allow_heuristic_search_form,
    should_stop_after_empty_meeting_directory,
    should_stop_after_page,
    should_stop_after_remembered_page,
)
from app.scraping.evidence import read_scrape_summary, write_scrape_evidence
from app.scraping.extract_meetings import extract_meetings_from_html
from app.scraping.interactions import perform_heuristic_interactions
from app.scraping.meeting_page_detector import score_html, score_link
from app.scraping.models import (
    BrowserActionTrace,
    CrawlSettings,
    ExtractedMeeting,
    ScrapedPage,
    ScrapeSourceResult,
)
from app.scraping.scoring import review_code_for_confidence
from app.sources.registry import Source


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


def test_extract_simple_tabbed_day_schedule() -> None:
    rows = [
        "\tBegining of the Trail\tCondon\t"
        "United Church of Christ 110 S Church St, Condon, OR 97823\t7:00 pm\t",
        "\tPendleton Nooner\tPendleton\t"
        "AA Club House 116 SE 12th, Pendleton, Oregon\t12:00 pm\t",
    ]
    html = f"""
    <main>
      <h2>Monday</h2>
      <pre>{rows[0]}</pre>
      <pre>{rows[1]}</pre>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings",
    )

    assert [meeting.method for meeting in meetings] == [
        "heuristic_simple_tabbed_day_schedule",
        "heuristic_simple_tabbed_day_schedule",
    ]
    assert meetings[0].payload["name"] == "Begining of the Trail"
    assert meetings[0].payload["city"] == "Condon"
    assert meetings[0].payload["day"] == "Monday"
    assert meetings[0].confidence >= 0.82


def test_extract_labelled_detail_blocks() -> None:
    html = """
    <main>
      <p>Name:</p>
      <p>Old Timer Speaker Meeting</p>
      <p>Town:</p>
      <p>Hermiston</p>
      <p>Location:</p>
      <p>Hermiston AA Hall</p>
      <p>680 Harper Road, Hermiston, Oregon</p>
      <p>Schedule:</p>
      <p>4th Saturday of every month</p>
      <p>Time:</p>
      <p>6:00 pm</p>
      <p>Attributes:</p>
      <p>Open</p>
      <p>Speaker Meeting</p>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings",
    )

    assert len(meetings) == 1
    assert meetings[0].method == "heuristic_labelled_detail_block"
    assert meetings[0].payload["name"] == "Old Timer Speaker Meeting"
    assert meetings[0].payload["day"] == "Saturday"
    assert meetings[0].payload["venue_name"] == "Hermiston AA Hall"
    assert meetings[0].payload["address_line1"] == "680 Harper Road, Hermiston, Oregon"
    assert meetings[0].confidence >= 0.82


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


def test_extract_meetings_from_classed_rows_with_location_context() -> None:
    html = """
    <main>
      <div class="location-block">
        <div class="location-header">
          <span class="location-badge">Texarkana AR</span>
          <a href="/new-freedom.html" class="location-name">New Freedom</a>
          <span class="location-addr">3911 B Quonset Dr, Texarkana AR 71854</span>
        </div>
        <div class="meeting-rows">
          <div class="meeting-row">
            <span class="meeting-day">Monday</span>
            <span class="meeting-time">12:00 pm</span>
            <span class="meeting-name">Open Topic</span>
            <span class="meeting-type">Open</span>
          </div>
          <div class="meeting-row">
            <span class="meeting-day">Tuesday</span>
            <span class="meeting-time">8:00 pm</span>
            <span class="meeting-name">Living Clean Book Study</span>
            <span class="meeting-type">Open</span>
          </div>
        </div>
      </div>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/",
    )

    assert [meeting.method for meeting in meetings] == [
        "heuristic_classed_meeting_row",
        "heuristic_classed_meeting_row",
    ]
    assert meetings[0].payload["day"] == "Monday"
    assert meetings[0].payload["time"] == "12:00 pm"
    assert meetings[0].payload["name"] == "Open Topic"
    assert meetings[0].payload["venue_name"] == "New Freedom"
    assert meetings[0].payload["address_line1"] == "3911 B Quonset Dr, Texarkana AR 71854"


def test_extract_meetings_from_heading_schedule_table() -> None:
    html = """
    <main>
      <table>
        <tr><th colspan="8">NA Serenity Group at Sabana Liber 8, Noord</th></tr>
        <tr><td>Monday</td><td>20:00 PM</td></tr>
        <tr><td>Wednesday</td><td>20:00 PM</td></tr>
      </table>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/",
    )

    assert [meeting.method for meeting in meetings] == [
        "heuristic_heading_schedule_table",
        "heuristic_heading_schedule_table",
    ]
    assert meetings[0].payload["name"] == "NA Serenity Group"
    assert meetings[0].payload["address_line1"] == "Sabana Liber 8, Noord"
    assert meetings[0].payload["day"] == "Monday"
    assert meetings[0].payload["time"] == "20:00"


def test_extract_meetings_from_localized_schedule_matrix() -> None:
    html = """
    <main>
      <table>
        <thead>
          <tr><td></td><td class="monday">Пн</td><td class="tuesday">Вт</td></tr>
        </thead>
        <tbody>
          <tr><td colspan="3"><strong>Пятигорск</strong></td></tr>
          <tr>
            <td><strong>«NAдежда»</strong><br>г. Пятигорск,<br>ул. Московская, 14К1</td>
            <td>17:30</td>
            <td>19:00</td>
          </tr>
        </tbody>
      </table>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/",
    )

    assert [meeting.method for meeting in meetings] == [
        "heuristic_schedule_matrix_table",
        "heuristic_schedule_matrix_table",
    ]
    assert meetings[0].payload["day"] == "Monday"
    assert meetings[1].payload["day"] == "Tuesday"
    assert meetings[0].payload["name"] == "NAдежда"
    assert meetings[0].payload["city"] == "Пятигорск"
    assert "ул. Московская" in meetings[0].payload["address_line1"]


def test_extract_meetings_from_localized_location_time_sections() -> None:
    html = """
    <main>
      <section class="box">
        <header>
          <h2>Lokacija: Rožna ulica 2, Ljubljana (Cerkev sv. Jakoba)</h2>
        </header>
        <p><strong>Čas: Ponedeljek, torek, četrtek, petek, sobota in nedelja ob 19.00</strong></p>
      </section>
      <section class="box">
        <header>
          <h2>Lokacija: Knjižnica Fužine - Preglov trg 15, 1000 Ljubljana</h2>
        </header>
        <p><strong>Čas: Sreda ob 19h</strong></p>
      </section>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/",
    )

    assert [meeting.method for meeting in meetings] == [
        "heuristic_location_time_section",
        "heuristic_location_time_section",
        "heuristic_location_time_section",
        "heuristic_location_time_section",
        "heuristic_location_time_section",
        "heuristic_location_time_section",
        "heuristic_location_time_section",
    ]
    assert [meeting.payload["day"] for meeting in meetings[:3]] == [
        "Monday",
        "Tuesday",
        "Thursday",
    ]
    assert meetings[0].payload["time"] == "19:00"
    assert meetings[-1].payload["day"] == "Wednesday"
    assert meetings[-1].payload["time"] == "19:00"


def test_extract_meetings_from_tab_separated_schedule_text() -> None:
    html = """
    <main>
      <p>5</p>
      <p>
        \tSU04\t\tSunday\t6:45 AM\tOnline Early Birds\tOnline Only\t\t
        Sunland Park\tNM\t88063\tClosed\tWest\tOnline\t
      </p>
      <p>https://zoom.us/j/89727100190?pwd=260026</p>
      <p>\tMeeting I.D. : 897 2710 0190 | Password: 260026\t\t\t\t</p>
      <p>aaelpasotx</p>
      <p>6</p>
      <p>\tSU05\t\tSunday\t8:30 AM\tAlta Vista Men's Stag\t</p>
      <p>Bowling Family Recovery Center</p>
      <p>\t3501 Hueco St\tEl Paso\tTX\t79903\tClosed\tCentral\tDoor on Grama\t\t\t\t\t\t</p>
      <p>aaelpasotx</p>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/elp-meetings",
    )

    assert [meeting.method for meeting in meetings] == [
        "heuristic_tab_separated_schedule",
        "heuristic_tab_separated_schedule",
    ]
    assert meetings[0].payload["source_record_id"] == "SU04"
    assert meetings[0].payload["name"] == "Online Early Birds"
    assert meetings[0].payload["online_url"] == "https://zoom.us/j/89727100190?pwd=260026"
    assert "Password: 260026" in meetings[0].payload["phone_join_info"]
    assert meetings[1].payload["name"] == "Alta Vista Men's Stag"
    assert meetings[1].payload["venue_name"] == "Bowling Family Recovery Center"
    assert meetings[1].payload["address_line1"] == "3501 Hueco St"
    assert meetings[1].payload["city"] == "El Paso"
    assert meetings[1].payload["region"] == "TX"
    assert all(meeting.confidence >= 0.75 for meeting in meetings)


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


def test_extract_meetings_from_tsml_json_feed() -> None:
    html = """
    [
      {
        "id": 439,
        "name": "Keep it Real Mondays",
        "day": 1,
        "time": "10:30",
        "time_formatted": "10:30 am",
        "types": ["BE", "O"],
        "location": "21D Grant Street",
        "formatted_address": "21D Grant St, Inverness IV3 8BN, UK",
        "timezone": "Europe/London",
        "attendance_option": "in_person"
      }
    ]
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://cascotland.org.uk/wp-admin/admin-ajax.php?action=meetings",
    )

    assert len(meetings) == 1
    assert meetings[0].method == "tsml_json_feed"
    assert meetings[0].payload["source_record_id"] == "439"
    assert meetings[0].payload["day"] == "Monday"
    assert meetings[0].payload["time"] == "10:30 am"
    assert meetings[0].payload["venue_name"] == "21D Grant Street"
    assert meetings[0].payload["address_line1"] == "21D Grant St, Inverness IV3 8BN, UK"
    assert meetings[0].payload["timezone"] == "Europe/London"


def test_extract_meetings_from_rendered_tsml_table() -> None:
    html = """
    <div id="tsml">
      <table class="table table-striped">
        <thead>
          <tr>
            <th class="time">Time</th>
            <th class="name">Meeting</th>
            <th class="location_group">Location / Group</th>
            <th class="address">Address</th>
            <th class="region">Region</th>
            <th class="types">Types</th>
          </tr>
        </thead>
        <tbody id="meetings_tbody">
          <tr class="type-o attendance-in_person">
            <td class="time" data-sort="4-12:30-clydebank-methodist-church">
              <span>12:30 pm</span>
            </td>
            <td class="name">
              <a href="https://cascotland.org.uk/meetings/womens-c-a-meeting/">
                Women's C.A. Meeting
              </a>
            </td>
            <td class="location">
              <div class="location-name notranslate">Clydebank Methodist Church</div>
            </td>
            <td class="address notranslate">10 Main Street</td>
            <td class="region notranslate">Clydebank</td>
            <td class="types">Open</td>
          </tr>
        </tbody>
      </table>
    </div>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://cascotland.org.uk/meetings/",
    )

    assert len(meetings) == 1
    assert meetings[0].method == "tsml_rendered_table_row"
    assert meetings[0].payload["source_record_id"] == "womens-c-a-meeting"
    assert meetings[0].payload["day"] == "Thursday"
    assert meetings[0].payload["time"] == "12:30 pm"
    assert meetings[0].payload["venue_name"] == "Clydebank Methodist Church"
    assert meetings[0].payload["address_line1"] == "10 Main Street"


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


def test_extract_day_section_splits_inline_online_meeting_name() -> None:
    html = """
    <article>
      <div class="entry-content">
        <h3>Monday</h3>
        <p>7:00 AM Pacific: Wake Up Group Meeting ID: 970 0504 0229 Join Zoom Meeting: https://us06web.zoom.us/j/97005040229</p>
      </div>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/online-meetings",
    )

    assert len(meetings) == 1
    assert meetings[0].payload["name"] == "Wake Up Group"
    assert "Meeting ID: 970 0504 0229" in meetings[0].payload["phone_join_info"]
    assert meetings[0].payload["online_url"] == "https://us06web.zoom.us/j/97005040229"
    assert meetings[0].confidence >= 0.75


def test_extract_day_section_splits_inline_phone_meeting_name() -> None:
    html = """
    <article>
      <div class="entry-content">
        <h3>Tuesday</h3>
        <p>5:30 pm A Way Home - 12&amp;12 Study 425-436-6314 Passcode: 587867#</p>
      </div>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/telephone-meetings",
    )

    assert len(meetings) == 1
    assert meetings[0].payload["name"] == "A Way Home - 12&12 Study"
    assert "425-436-6314" in meetings[0].payload["phone_join_info"]
    assert "Passcode: 587867#" in meetings[0].payload["phone_join_info"]
    assert meetings[0].confidence >= 0.75


def test_extract_day_section_splits_inline_one_tap_mobile_details() -> None:
    html = """
    <article>
      <div class="entry-content">
        <h3>Tuesday</h3>
        <p>
          7:00 AM Pacific (M-F ) 7AM Coastside Group (Half Moon Bay)
          J oin Meeting: 7AM Coastside Group One tap mobile:
          +16699006833,,790124889# Dial by phone: 669-900-6833
          Meeting ID: 790 124 889
        </p>
      </div>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/online-meetings",
    )

    assert len(meetings) == 1
    assert meetings[0].payload["name"] == "Coastside Group (Half Moon Bay)"
    assert "One tap mobile" in meetings[0].payload["phone_join_info"]
    assert "Meeting ID: 790 124 889" in meetings[0].payload["phone_join_info"]
    assert meetings[0].confidence >= 0.75


def test_extract_day_section_recovers_name_before_connect_with_zoom() -> None:
    html = """
    <article>
      <div class="entry-content">
        <h3>Tuesday</h3>
        <p>
          7:00am - 8:00am Zoom Meeting Morning Medicine (O D)
          Connect with Zoom Meeting ID: 746 311 7995 Password: 4062014
          Dial (646) 558 8656
        </p>
      </div>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings",
    )

    assert len(meetings) == 1
    assert meetings[0].payload["name"] == "Morning Medicine (O D)"
    assert "Connect with Zoom" in meetings[0].payload["phone_join_info"]
    assert "Meeting ID: 746 311 7995" in meetings[0].payload["phone_join_info"]
    assert meetings[0].confidence >= 0.75


def test_extract_meetings_ignores_meeting_information_inline_detail() -> None:
    html = """
    <main>
      <p>Morning Serenity</p>
      <p>Meeting Information Sunday, 7:00 am In-person Online Daily Reflections</p>
      <p>Meeting Information</p>
      <p>Sunday, 7:00 am</p>
      <p>In-person</p>
      <p>Online</p>
      <p>Daily Reflections</p>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings/morning-serenity/",
    )

    assert all(meeting.payload.get("name") != "Meeting Information" for meeting in meetings)
    assert all(meeting.confidence >= 0.75 for meeting in meetings)


def test_extract_meetings_ignores_wordfence_timestamp_text() -> None:
    html = """
    <main>
      <p>Your access to this site has been limited by the site owner</p>
      <p>Your computer's time:</p>
      <p>Sun, 24 May 2026 11:56 GMT</p>
      <p>Generated by Wordfence at Sun, 24 May 2026 11:56 GMT.</p>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings/",
    )

    assert meetings == []


def test_extract_inline_schedule_ignores_event_heading_colon_name() -> None:
    html = """
    <main>
      <p>Upcoming Events</p>
      <p>BAY GROUP: MONDAY 8PM SPEAKER MEETING</p>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/",
    )

    assert meetings == []


def test_extract_day_section_splits_inline_labeled_remote_meeting_name() -> None:
    html = """
    <article>
      <div class="entry-content">
        <h3>Wednesday</h3>
        <p>
          Wednesday Men's Stag Type: Closed / Hybrid Time: Wednesdays, 7pm
          https://us04web.zoom.us/j/457213547 Meeting ID: 457 213 547 password:1935
        </p>
      </div>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/remote-meetings",
    )

    assert len(meetings) == 1
    assert meetings[0].payload["name"] == "Wednesday Men's Stag"
    assert meetings[0].payload["online_url"] == "https://us04web.zoom.us/j/457213547"
    assert "Meeting ID: 457 213 547" in meetings[0].payload["phone_join_info"]
    assert "password:1935" in meetings[0].payload["phone_join_info"]
    assert meetings[0].confidence >= 0.75


def test_extract_day_section_splits_german_connection_markers() -> None:
    html = """
    <article>
      <div class="entry-content">
        <h3>Montag</h3>
        <p>19:00 Uhr Mainz Telefonmeeting 03052014351 Pin 122612#</p>
      </div>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/onlinemeetings/termin-gebunden/",
    )

    assert len(meetings) == 1
    assert meetings[0].payload["name"] == "Mainz"
    assert "Telefonmeeting 03052014351" in meetings[0].payload["phone_join_info"]
    assert "Pin 122612#" in meetings[0].payload["phone_join_info"]
    assert meetings[0].confidence >= 0.75


def test_extract_day_section_keeps_zoom_name_before_german_meeting_id() -> None:
    html = """
    <article>
      <div class="entry-content">
        <h3>Mittwoch</h3>
        <p>19:30 Uhr Zoom-Beginner-Meeting Zoom Meetings ID: 242 424 1313 Passwort anfragen</p>
      </div>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/onlinemeetings/termin-gebunden/",
    )

    assert len(meetings) == 1
    assert meetings[0].payload["name"] == "Zoom-Beginner-Meeting"
    assert "Zoom Meetings ID: 242 424 1313" in meetings[0].payload["phone_join_info"]
    assert meetings[0].confidence >= 0.75


def test_extract_day_section_splits_german_dial_in_code() -> None:
    html = """
    <article>
      <div class="entry-content">
        <h3>Samstag</h3>
        <p>08:00 Uhr AArlybird Literaturmeeting Einwahl-Nr. : Germany 030 52014351 Code: 758449#</p>
      </div>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/onlinemeetings/termin-gebunden/",
    )

    assert len(meetings) == 1
    assert meetings[0].payload["name"] == "AArlybird Literaturmeeting"
    assert "Einwahl-Nr. : Germany 030 52014351" in meetings[0].payload["phone_join_info"]
    assert "Code: 758449#" in meetings[0].payload["phone_join_info"]
    assert meetings[0].confidence >= 0.75


def test_extract_day_section_applies_meeting_page_context_to_schedule_rows() -> None:
    html = """
    <main>
      <div class="entry-content">
        <h1>Grupo 2 De Febrero</h1>
        <p>Meeting Information</p>
        <p>Saturday 7:00 PM - 8:30 PM PDT</p>
        <p>In-person</p>
        <p>Open</p>
        <p>Spanish</p>
        <p>TEL: (831)613-2339. (831)776-2023.</p>
        <p>321 El Camino Real, Greenfield, CA 93927, USA</p>
        <p>Greenfield</p>
        <h3>Monday</h3>
        <p>7:00 PM Grupo 2 De Febrero</p>
      </div>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings/grupo-2-de-febrero/",
    )

    assert len(meetings) == 1
    assert meetings[0].payload["name"] == "Grupo 2 De Febrero"
    assert meetings[0].payload["address_line1"] == "321 El Camino Real, Greenfield, CA 93927, USA"
    assert meetings[0].payload["city"] == "Greenfield"
    assert "TEL: (831)613-2339. (831)776-2023." in meetings[0].payload["phone_join_info"]
    assert meetings[0].confidence >= 0.75


def test_extract_day_section_splits_inline_location_meeting_name() -> None:
    html = """
    <article>
      <div class="entry-content">
        <h3>Sunday</h3>
        <p>8:00 AM : Westside AA , Sioux Falls, SD, 57104 | Big Book</p>
        <p>9am A Daily Reprieve (LT) 723 Slocum St. Lancaster</p>
      </div>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meeting-times",
    )

    assert [meeting.payload["name"] for meeting in meetings] == [
        "Westside AA",
        "A Daily Reprieve (LT)",
    ]
    assert meetings[0].payload["address_line1"] == "Sioux Falls, SD, 57104"
    assert meetings[1].payload["address_line1"] == "723 Slocum St. Lancaster"
    assert all(meeting.confidence >= 0.75 for meeting in meetings)


def test_extract_meetings_from_accordion_day_panels() -> None:
    html = """
    <div class="panel">
      <div class="panel-title"><a class="wb-accordion-title"><div>Monday</div></a></div>
      <div class="panel-body">
        <p><strong>6:00pm - 7:00pm</strong></p>
        <p><strong>Going Forward - Kelowna</strong></p>
        <p>Location: 1169 Sutherland Avenue, Kelowna BC</p>
        <p>&nbsp;</p>
        <p><strong>7:00pm - 8:30pm</strong></p>
        <p><strong>Light Side - Chilliwack</strong></p>
        <p>Location: Community Hall</p>
      </div>
    </div>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings",
    )

    assert len(meetings) == 2
    assert meetings[0].payload["day"] == "Monday"
    assert meetings[0].payload["time"] == "6:00pm"
    assert meetings[0].payload["name"] == "Going Forward - Kelowna"
    assert meetings[0].payload["address_line1"] == "1169 Sutherland Avenue, Kelowna BC"
    assert meetings[1].payload["address_line1"] == "Community Hall"


def test_extract_meetings_from_polish_day_sections() -> None:
    html = """
    <article>
      <div class="entry-content">
        <h2>PONIEDZIAŁEK</h2>
        <p>Grupa “Po prostu przyjdź”</p>
        <p>Każdy Poniedziałek o godzinie: PL 19:30</p>
        <p>Adres: Warszawa ul. Aleje Jerozolimskie 99/40</p>
        <p>Jest Rozwiązanie (mityng hybrydowy)</p>
        <p>Każdy Poniedziałek o godzinie: PL 20:00 UK 19:00</p>
        <p>Adres: YMCA - Hinton Room, 56 Westover Rd, Bournemouth</p>
        <p>Zoom: Meeting ID: 874 3213 3552 Hasło: 441475 Aktywny link</p>
      </div>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://ca-polska.org/spotkania/",
    )

    assert [meeting.payload["name"] for meeting in meetings] == [
        "Po prostu przyjdź",
        "Jest Rozwiązanie",
    ]
    assert meetings[0].payload["day"] == "Poniedziałek"
    assert meetings[0].payload["time"] == "19:30"
    assert meetings[0].payload["address_line1"] == "Warszawa ul. Aleje Jerozolimskie 99/40"
    assert meetings[1].payload["time"] == "20:00"
    assert "Hasło: 441475" in meetings[1].payload["phone_join_info"]
    assert "Aktywny link" not in meetings[1].payload["phone_join_info"]


def test_extract_meetings_from_world_service_direct_listing() -> None:
    html = """
    <article>
      <div class="entry-content">
        <p><strong>Wednesday 5:30 pm | City Playa Del Carmen</strong><br>
        NA clubhouse<br>
        The North/West corner of Calle/Street 30 and Ave 35<br>
        Contact # 1-732-261-8314</p>
        <p><strong>English CA Cancun meetings</strong></p>
        <p><strong>Tuesday 5:00 pm - 6:00 pm</strong><br>
        <strong>XYZ32</strong><br>
        <a href="https://maps.example.test/place">Av Carlos just Nadar sm5 mz8</a><br>
        Step and tradition study</p>
        <p><strong>Thursday 5:00 pm - 6:00 pm</strong> - Big Book study<br>
        <strong>Desert in the Oasis Futility</strong><br>
        <a href="https://maps.example.test/place">Av Carlos just Nadar sm5 mz8</a></p>
      </div>
    </article>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://ca.org/meetings/mexico/",
    )

    assert [meeting.method for meeting in meetings] == [
        "heuristic_direct_listing",
        "heuristic_direct_listing",
        "heuristic_direct_listing",
    ]
    assert meetings[0].payload["day"] == "Wednesday"
    assert meetings[0].payload["time"] == "5:30 pm"
    assert meetings[0].payload["city"] == "Playa Del Carmen"
    assert "1-732-261-8314" in meetings[0].payload["phone_join_info"]
    assert meetings[1].payload["name"] == "XYZ32"
    assert meetings[1].payload["address_line1"] == "Av Carlos just Nadar sm5 mz8"
    assert meetings[2].payload["name"] == "Desert in the Oasis Futility"


def test_extract_meetings_from_rendered_structured_text_list() -> None:
    html = """
    <pre>
    Number found:
    All meetings open 15 to 30 minutes prior to their start time indicated.
    C.A. Bachelor's Walk
    (1) Monday
    1:00 pm
    Online
    All Ireland
    Beginners / Newcomers Meeting
    Zoom Link: Click Here
    Access Code: 733 233 3432
    Passcode: cabachelor
    Attendance is limited to C.A. members and those with a desire to stop using cocaine.
    C.A. Oz House
    (1) Monday
    3:00 pm
    In-person
    Co. Galway
    Big Book Study Meeting
    Ozanam House, Room 3, St. Augustine Street, Galway, H91 V3PV
    Enter by blue door on the left.
    Attendance is limited to C.A. members and those with a desire to stop using cocaine.
    </pre>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://www.caireland.live/meeting-schedule",
    )

    assert [meeting.method for meeting in meetings] == [
        "heuristic_structured_text_list",
        "heuristic_structured_text_list",
    ]
    assert meetings[0].payload["name"] == "C.A. Bachelor's Walk"
    assert meetings[0].payload["day"] == "Monday"
    assert meetings[0].payload["phone_join_info"] == (
        "Zoom Link: Click Here Access Code: 733 233 3432 Passcode: cabachelor"
    )
    assert meetings[1].payload["attendance_option"] == "In-person"
    assert meetings[1].payload["address_line1"] == (
        "Ozanam House, Room 3, St. Augustine Street, Galway, H91 V3PV"
    )


def test_wix_data_items_convert_to_structured_text_meetings() -> None:
    text = _wix_data_items_to_text(
        [
            {
                "data": {
                    "title": "C.A. Bachelor's Walk",
                    "requirements": "(1) Monday",
                    "time": "1:00 pm",
                    "jobType1": "Online",
                    "county": "All Ireland",
                    "jobDescription": "Beginners / Newcomers Meeting",
                    "location": (
                        '<p><a href="https://example.test">Zoom Link: Click Here</a></p>'
                        "<p>Access Code: 733 233 3432</p>"
                    ),
                }
            }
        ]
    )

    meetings = extract_meetings_from_html(
        f"<pre>{text}</pre>",
        source_page_url="https://www.caireland.live/meeting-schedule",
    )

    assert len(meetings) == 1
    assert meetings[0].payload["name"] == "C.A. Bachelor's Walk"
    assert meetings[0].payload["phone_join_info"] == (
        "Zoom Link: Click Here Access Code: 733 233 3432"
    )


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


def test_extract_meetings_from_rendered_landing_page_sequence_text() -> None:
    html = """
    <div data-rendered-text-fallback="true"><pre>
    MEETINGS

    More Info

    Address:

    1161 Sherburne Ave

    Saint Paul, MN 55104

    NEW MEETING

    Sufficient Substitute

    Tuesdays at 7:30 pm

    (in person)

    Begins August 19, 2025

    Upfront Alano Clubhouse

    302 4th Ave N.E.

    Brainard, MN 56401

    612-889-6916

    More Info

    "My Pen is Not A Pusher"

    Friday 7:00 P.M

    St Paul

    "Recovery is Not and Chore"

    Wednesday 7:15 PM

    St Paul
    </pre></div>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://www.caminnesota.org/",
    )

    assert [meeting.method for meeting in meetings] == [
        "heuristic_sequence_text",
        "heuristic_sequence_text",
        "heuristic_sequence_text",
    ]
    assert meetings[0].payload["name"] == "Sufficient Substitute"
    assert meetings[0].payload["day"] == "Tuesday"
    assert meetings[0].payload["time"] == "7:30 pm"
    assert meetings[0].payload["venue_name"] == "Upfront Alano Clubhouse"
    assert meetings[0].payload["address_line1"] == "302 4th Ave N.E."
    assert meetings[0].payload["city"] == "Brainard, MN 56401"
    assert meetings[0].payload["phone_join_info"] == "612-889-6916"
    assert meetings[1].payload["name"] == "My Pen is Not A Pusher"
    assert meetings[1].payload["day"] == "Friday"
    assert meetings[1].payload["city"] == "St Paul"
    assert meetings[2].payload["name"] == "Recovery is Not and Chore"


def test_extract_meetings_from_rendered_filter_column_text() -> None:
    html = """
    <div data-rendered-text-fallback="true"><pre>
    Meetings
    Search
    Anywhere
    Any Day
    Any Time
    Any Type
    List
    Map
    Time
    Name
    Location / Group
    Address / Platform
    Region
    4 meetings in progress
    8:00 pm
    Saturday
    The Emerywood Group, As Bill Sees It
    Emerywood Baptist Church
    1300 Country Club Drive
    High Point
    9:00 am
    Sunday
    Conscious Contact
    Wesley Memorial Methodist Church
    1225 Chestnut Drive
    High Point
    AA ONLINE MEETINGS EVERYWHERE
    </pre></div>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://www.aanc24.org/meetings/find-a-meeting",
    )

    assert [meeting.method for meeting in meetings] == [
        "heuristic_rendered_column_text",
        "heuristic_rendered_column_text",
    ]
    assert meetings[0].payload["name"] == "The Emerywood Group, As Bill Sees It"
    assert meetings[0].payload["day"] == "Saturday"
    assert meetings[0].payload["time"] == "8:00 pm"
    assert meetings[0].payload["venue_name"] == "Emerywood Baptist Church"
    assert meetings[0].payload["address_line1"] == "1300 Country Club Drive"
    assert meetings[0].payload["region"] == "High Point"


def test_extract_meetings_from_rendered_iframe_tabbed_column_text() -> None:
    html = """
    <div data-rendered-text-fallback="true"><pre>
    Meetings
    Time\tName\tLocation / Group\tAddress / Platform\tRegion
    4 meetings in progress

    8:00 pm
    Saturday
    \tThe Emerywood Group, As Bill Sees It\tEmerywood Baptist Church\t
    1300 Country Club Drive
    \tHigh Point

    7:30 pm
    Sunday
    \tForest Hills Group\tForest Hills Presbyterian Church\t
    836 W Lexington Avenue
    Zoom
    \tHigh Point
    </pre></div>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://www.aanc24.org/meetings/find-a-meeting",
    )

    assert len(meetings) == 2
    assert meetings[0].payload["name"] == "The Emerywood Group, As Bill Sees It"
    assert meetings[1].payload["name"] == "Forest Hills Group"
    assert meetings[1].payload["phone_join_info"] == "Zoom"
    assert meetings[1].payload["region"] == "High Point"


def test_extract_meetings_normalizes_homepage_dot_and_compact_times() -> None:
    html = """
    <main>
      <p><strong>Chiang Mai Group</strong><br>
      Saturday 4.30pm<br>
      Oyes smoothie<br>
      No. 27, 1 Hussadhisawee Road, Chiang Mai 50300</p>

      <p><strong>Friday morning</strong><br>
      Time: 9.30am -10.30am - Speaker topic meeting<br>
      SEASHELL restaurant&amp;bar<br>
      58/3 Moo 8 Koh Phangan</p>

      <p><strong>Bangkok Group</strong><br>
      Every Sunday at 930am<br>
      Bangkok Recovery Club<br>
      13 Soi Preeda Bangkok</p>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://cathailand.org/",
    )

    assert [meeting.payload["time"] for meeting in meetings] == ["4:30pm", "9:30am", "9:30am"]
    assert meetings[0].payload["day"] == "Saturday"
    assert meetings[1].payload["day"] == "Friday"
    assert meetings[2].payload["day"] == "Sunday"


def test_extract_meetings_from_inline_landing_page_schedule() -> None:
    html = """
    <main>
      <h3>CA OSLO - KRYPTEN mandag kl. 20-21 (åpner kl. 19)
      fredag kl. 20-21 (åpner kl. 19) Holtegata 15, 0259 Oslo</h3>
      <h3>DO OR DIE - MAJORSTUEN tirsdag 18:00-19:00 Rosenborggata 3, 0356 Oslo</h3>
      <h3>CA ONLINE - GI DET VIDERE onsdag kl. 19-20
      Zoom møte-ID: 85603686376 https://us06web.zoom.us/j/85603686376#success</h3>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://www.ca-norge.no/",
    )

    assert [meeting.payload["name"] for meeting in meetings] == [
        "CA OSLO - KRYPTEN",
        "CA OSLO - KRYPTEN",
        "DO OR DIE - MAJORSTUEN",
        "CA ONLINE - GI DET VIDERE",
    ]
    assert [meeting.payload["day"] for meeting in meetings] == [
        "Mandag",
        "Fredag",
        "Tirsdag",
        "Onsdag",
    ]
    assert [meeting.payload["time"] for meeting in meetings] == [
        "20:00",
        "20:00",
        "18:00",
        "19:00",
    ]
    assert meetings[0].payload["address_line1"] == "Holtegata 15, 0259 Oslo"
    assert meetings[2].payload["address_line1"] == "Rosenborggata 3, 0356 Oslo"
    assert meetings[3].payload["online_url"] == "https://us06web.zoom.us/j/85603686376#success"
    assert {meeting.method for meeting in meetings} == {"heuristic_inline_schedule"}
    assert all(meeting.confidence >= 0.75 for meeting in meetings)


def test_day_section_rejects_time_range_fragments_as_locations() -> None:
    html = """
    <main>
      <p>Tuesday 7:00pm to 8:30pm</p>
      <p>Wednesday 7:00pm 7 : - 8:30pm</p>
      <p>Friday 8-9 PM</p>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/meetings",
    )

    assert meetings == []


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

    assert [link["url"] for link in prioritized] == ["https://example.org/find-a-meeting"]
    assert is_allowed_url("https://example.org/", "https://meetings.example.org/list")
    assert not is_allowed_url("https://example.org/", "https://external.test/meetings")
    assert not is_allowed_url("https://example.org/", "https://example.org/feed/bmlt2ics/")
    assert not is_allowed_url(
        "https://example.org/",
        "https://example.org/?current-meeting-list=7",
    )
    assert is_allowed_url(
        "https://example.org/?current-meeting-list=7",
        "https://example.org/?current-meeting-list=7",
    )


async def test_crawler_collects_alternate_json_meeting_feed() -> None:
    class FakePage:
        async def eval_on_selector_all(self, selector: str, script: str) -> list[dict[str, str]]:
            assert "link[rel~='alternate'][type='application/json'][href]" in selector
            assert "[data-url]" in selector
            assert "links.map" in script
            return [
                {
                    "url": "/wp-admin/admin-ajax.php?action=meetings",
                    "text": "Meetings Feed",
                }
            ]

    links = await _page_links(FakePage(), "https://example.org/meetings/")
    prioritized = prioritize_links("https://example.org/", links)

    assert links == [
        {
            "url": "https://example.org/wp-admin/admin-ajax.php?action=meetings",
            "text": "Meetings Feed",
        }
    ]
    assert prioritized == links


async def test_crawler_converts_tsml_filter_links_to_json_feed() -> None:
    class FakePage:
        async def eval_on_selector_all(self, selector: str, script: str) -> list[dict[str, str]]:
            assert "link[rel~='alternate'][type='application/json'][href]" in selector
            assert "[data-url]" in selector
            assert "links.map" in script
            return [
                {
                    "url": "/meetings/?tsml-day=any&tsml-district=kent",
                    "text": "Meetings",
                }
            ]

    links = await _page_links(FakePage(), "https://meetings.cakent.org/")

    assert links == [
        {
            "url": (
                "https://meetings.cakent.org/wp-admin/admin-ajax.php?"
                "action=meetings&district=kent"
            ),
            "text": "Meetings",
        }
    ]


def test_crawler_detects_tsml_json_feed_url() -> None:
    html = """
    <html>
      <head>
        <link rel="alternate" type="application/json" title="Meetings Feed"
          href="/wp-admin/admin-ajax.php?action=meetings">
      </head>
    </html>
    """

    feed_url = _tsml_json_feed_url_from_html(html, "https://example.org/meetings/")

    assert feed_url == "https://example.org/wp-admin/admin-ajax.php?action=meetings"


def test_crawler_detects_tsml_data_src_feed_url() -> None:
    html = """
    <html>
      <body>
        <div id="tsml-ui"
          data-src="https://caws-api.azurewebsites.net/api/v1/meetings-tsml?area=Ohio">
        </div>
      </body>
    </html>
    """

    feed_url = _tsml_json_feed_url_from_html(html, "https://caohioarea.org/")

    assert feed_url == "https://caws-api.azurewebsites.net/api/v1/meetings-tsml?area=Ohio"


def test_crawler_carries_tsml_page_filters_to_json_feed_url() -> None:
    html = """
    <html>
      <head>
        <link rel="alternate" type="application/json" title="Meetings Feed"
          href="/wp-admin/admin-ajax.php?action=meetings">
      </head>
    </html>
    """

    feed_url = _tsml_json_feed_url_from_html(
        html,
        "https://meetings.cakent.org/meetings/?tsml-day=any&tsml-district=kent",
    )

    assert (
        feed_url
        == "https://meetings.cakent.org/wp-admin/admin-ajax.php?action=meetings&district=kent"
    )


async def test_crawler_fetches_json_feed_text() -> None:
    class FakePage:
        async def evaluate(self, script: str, url: str) -> dict[str, object]:
            assert "fetch(url" in script
            assert url == "https://example.org/wp-admin/admin-ajax.php?action=meetings"
            return {"status": 200, "contentType": "application/json", "text": '[{"id": 1}]'}

    text = await _fetch_json_feed_text(
        FakePage(),
        "https://example.org/wp-admin/admin-ajax.php?action=meetings",
    )

    assert text == '[{"id": 1}]'


def test_crawler_prioritizes_public_meeting_tabs_over_service_pages() -> None:
    links = [
        {
            "url": "https://forms.cocaineanonymous.org.uk/start-a-meeting/",
            "text": "Register a new meeting",
        },
        {
            "url": "https://cocaineanonymous.org.uk/service-meetings/",
            "text": "Service meetings",
        },
        {
            "url": "https://meetings.cocaineanonymous.org.uk/meetings/?tsml-attendance_option=in_person",
            "text": "Find a face-to-face meeting",
        },
    ]

    prioritized = prioritize_links("https://www.cocaineanonymous.org.uk/", links)
    urls = [link["url"] for link in prioritized]

    assert urls[:2] == [
        "https://meetings.cocaineanonymous.org.uk/meetings/?tsml-attendance_option=in_person",
    ]
    assert "https://cocaineanonymous.org.uk/service-meetings/" not in urls
    assert "https://forms.cocaineanonymous.org.uk/start-a-meeting/" not in urls


def test_crawler_prioritizes_ireland_meeting_schedule_tab() -> None:
    links = [
        {"url": "https://www.caireland.live/events", "text": "Events"},
        {"url": "https://www.caireland.live/meeting-schedule", "text": "Meetings"},
        {"url": "https://www.caireland.live/contact", "text": "Contact"},
    ]

    prioritized = prioritize_links("https://www.caireland.live/", links)

    assert [link["url"] for link in prioritized] == [
        "https://www.caireland.live/meeting-schedule"
    ]


def test_crawler_prioritizes_child_schedule_links_before_global_menu() -> None:
    links = [
        {"url": "https://najapan.org/meeting/hokkaido/mon/", "text": "月曜日"},
        {"url": "https://najapan.org/meeting/kanto/mon/", "text": "月曜日"},
        {"url": "https://najapan.org/meeting/kanto/tue/", "text": "火曜日"},
    ]

    prioritized = prioritize_links("https://najapan.org/meeting/kanto/", links)

    assert [link["url"] for link in prioritized[:2]] == [
        "https://najapan.org/meeting/kanto/mon/",
        "https://najapan.org/meeting/kanto/tue/",
    ]
    assert "https://najapan.org/meeting/hokkaido/mon/" not in [
        link["url"] for link in prioritized
    ]


def test_crawler_prioritizes_aa_groups_links() -> None:
    links = [
        {"url": "https://example.org/service", "text": "Service"},
        {"url": "https://example.org/groups", "text": "AA Groups"},
        {"url": "https://example.org/contact", "text": "Contact"},
    ]

    prioritized = prioritize_links("https://example.org/", links)

    assert [link["url"] for link in prioritized] == ["https://example.org/groups"]


def test_crawler_filters_meeting_list_pdfs() -> None:
    links = [
        {
            "url": "https://example.org/files/May_NA_Meeting_List.pdf",
            "text": "Current meeting list",
        },
        {
            "url": "https://example.org/files/newsletter.pdf",
            "text": "Newsletter",
        },
        {
            "url": "https://example.org/files/service-minutes.pdf",
            "text": "Service minutes",
        },
        {
            "url": "https://na.org/wp-content/uploads/2024/05/EN3129-IP-29-English.pdf",
            "text": "An Introduction to NA Meetings",
        },
        {
            "url": "https://najapan.org/chubu/meeting/chubu.pdf",
            "text": "中部エリアミーティングリスト・略図付き（PDF）",
        },
        {
            "url": "https://example.org/?current-meeting-list=1",
            "text": "Print Meeting List",
        },
        {
            "url": "https://img1.wsimg.com/downloads/Meetings%20Updated%2012%205%2025.pdf?ver=1",
            "text": "Download",
        },
    ]

    assert _meeting_pdf_links(links) == [
        {
            "url": "https://example.org/files/May_NA_Meeting_List.pdf",
            "text": "Current meeting list",
        },
        {
            "url": "https://najapan.org/chubu/meeting/chubu.pdf",
            "text": "中部エリアミーティングリスト・略図付き（PDF）",
        },
        {
            "url": "https://example.org/?current-meeting-list=1",
            "text": "Print Meeting List",
        },
        {
            "url": "https://img1.wsimg.com/downloads/Meetings%20Updated%2012%205%2025.pdf?ver=1",
            "text": "Download",
        },
    ]


def test_extracts_plain_text_meetings_from_pdf_fallback() -> None:
    html = _html_with_pdf_text(
        """
        Meetings:
        Monday:
        7:00 - 8:00pm
        "Last House on the Block"
        1st Baptist Franklin
        318 Hall St
        Franklin, VA 23851
        Contact: Mike T. 267.414.7266
        Tuesday:
        7:00 - 8:00pm
        "Earthbound Group"
        Emmanuel Episcopal Church
        400 N. High Street
        Franklin VA 23851
        """
    )

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://outer.example.org/meeting-list.pdf",
    )

    assert len(meetings) == 2
    assert meetings[0].method == "heuristic_pdf_text"
    assert meetings[0].payload["name"] == "Last House on the Block"
    assert meetings[0].payload["venue_name"] == "1st Baptist Franklin"
    assert meetings[0].payload["address_line1"] == "318 Hall St"
    assert meetings[1].payload["day"] == "Tuesday"


def test_extracts_bmlt_printable_pdf_lines() -> None:
    html = _html_with_pdf_text(
        """
        SUNDAY
        Sunday Morning Survival; 10:00 AM, Shar Academy, 1851
        W Grand Blvd, Detroit, MI, 48208 (O)
        MONDAY
        NOON-1:00PM
        Nooners (O,To), Grace Bible Fellowship House, 317 S. 5th Ave, Yuma, AZ, 85364
        """
    )

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://example.org/?current-meeting-list=1",
    )

    assert len(meetings) == 2
    assert meetings[0].payload["name"] == "Sunday Morning Survival"
    assert meetings[0].payload["venue_name"] == "Shar Academy, 1851"
    assert meetings[0].payload["address_line1"] == "W Grand Blvd, Detroit, MI, 48208 (O)"
    assert meetings[1].payload["name"] == "Nooners"
    assert meetings[1].payload["time"] == "12:00 pm"
    assert meetings[1].payload["address_line1"] == (
        "Grace Bible Fellowship House, 317 S. 5th Ave, Yuma, AZ, 85364"
    )


def test_extracts_japanese_pdf_meeting_rows() -> None:
    html = _html_with_pdf_text(
        """
        中部エリア・ミーティング
        曜日
        最寄り駅
        月曜
        本山
        月の風
        19:00～20:30
        オープン
        １P
        東別院
        Ｓｔｅｐ Ｗｏｒｋｓ
        19:00～20:00
        オープン/O/＊/＃/P/§
        1P
        """
    )

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://najapan.org/chubu/meeting/chubu.pdf",
    )

    assert len(meetings) == 2
    assert meetings[0].payload["day"] == "Monday"
    assert meetings[0].payload["time"] == "19:00"
    assert meetings[0].payload["name"] == "月の風"
    assert meetings[0].payload["venue_name"] == "本山"
    assert meetings[1].payload["name"] == "Ｓｔｅｐ Ｗｏｒｋｓ"


def test_extracts_japanese_paragraph_meeting_blocks() -> None:
    html = """
    <main>
      <h1>月曜日・関東エリア</h1>
      <div class="entry-content">
        <p>●東大宮</p>
        <p>
          時間：19:30～20:30<br>
          会場：東大宮コミュニティセンター3階<br>
          場所：さいたま市見沼区東大宮4-31-17<br>
          形式：オープンミーティング
        </p>
        <p>info：09026362544<br>(埼玉グループ）</p>
        <hr>
        <p>●香川県高松市</p>
        <p>
          さぬきグループ<br>
          午後 7:00～8：30<br>
          高松市男女共同参画センター<br>
          住所：高松市錦町1丁目20-11<br>
          オープン O
        </p>
      </div>
    </main>
    """

    meetings = extract_meetings_from_html(
        html,
        source_page_url="https://najapan.org/meeting/kanto/mon/",
    )

    assert [meeting.method for meeting in meetings] == [
        "heuristic_japanese_paragraph",
        "heuristic_japanese_paragraph",
    ]
    assert meetings[0].payload["day"] == "Monday"
    assert meetings[0].payload["time"] == "19:30"
    assert meetings[0].payload["name"] == "東大宮"
    assert meetings[0].payload["venue_name"] == "東大宮コミュニティセンター3階"
    assert meetings[0].payload["address_line1"] == "さいたま市見沼区東大宮4-31-17"
    assert meetings[1].payload["time"] == "19:00"
    assert meetings[1].payload["name"] == "さぬきグループ"
    assert meetings[1].payload["city"] == "香川県高松市"


def test_crawler_detects_downloadable_meeting_list_url() -> None:
    assert _looks_like_downloadable_meeting_list_url(
        "https://example.org/?current-meeting-list=1"
    )
    assert not _looks_like_downloadable_meeting_list_url("https://example.org/meetings/")


def test_crawler_decodes_google_calendar_embed_to_ics_url() -> None:
    urls = _google_calendar_ics_urls(
        [
            (
                "https://calendar.google.com/calendar/embed?"
                "src=NTR1cjdhNXFhazc0NTA0cDIxZnFoYmpya2tAZ3JvdXAuY2FsZW5kYXIuZ29vZ2xlLmNvbQ"
            )
        ]
    )

    assert urls == [
        (
            "https://calendar.google.com/calendar/ical/"
            "54ur7a5qak74504p21fqhbjrkk@group.calendar.google.com/public/basic.ics"
        )
    ]


def test_extracts_weekly_meetings_from_google_calendar_ics() -> None:
    ics = """BEGIN:VCALENDAR
X-WR-TIMEZONE:America/Boise
BEGIN:VEVENT
DTSTART;TZID=America/Boise:20260217T190000
DTEND;TZID=America/Boise:20260217T200000
RRULE:FREQ=WEEKLY;BYDAY=TU
UID:meeting-1@example
LOCATION:909 Main St\\, Salmon\\, ID 83467\\, USA
SUMMARY:SALMON - NA Meeting
DESCRIPTION:Open\\nWheelchair
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/Boise:20260426T193000
RRULE:FREQ=WEEKLY;BYDAY=SU
UID:event-1@example
LOCATION:123 Main St\\, Boise\\, ID
SUMMARY:Area Service Workshop
END:VEVENT
END:VCALENDAR
"""

    meetings = _extract_google_calendar_ics_meetings(
        ics,
        "https://calendar.google.com/calendar/ical/example/public/basic.ics",
    )

    assert len(meetings) == 1
    assert meetings[0].payload["name"] == "SALMON - NA Meeting"
    assert meetings[0].payload["day"] == "Tuesday"
    assert meetings[0].payload["time"] == "19:00"
    assert meetings[0].payload["timezone"] == "America/Boise"
    assert meetings[0].payload["address_line1"] == "909 Main St, Salmon, ID 83467, USA"


def test_crawler_prioritizes_meeting_locations_links() -> None:
    links = [
        {"url": "https://example.org/contact", "text": "Contact"},
        {"url": "https://example.org/meeting-locations", "text": "Meeting Locations"},
    ]

    prioritized = prioritize_links("https://example.org/", links)

    assert [link["url"] for link in prioritized] == [
        "https://example.org/meeting-locations"
    ]


def test_crawler_starts_with_source_before_targeted_discovery() -> None:
    queue = initial_crawl_queue("https://www.caireland.live/")
    urls = [url for url, _depth in queue]

    assert urls == ["https://www.caireland.live/"]


def test_crawler_starts_with_remembered_successful_pages() -> None:
    queue = initial_crawl_queue(
        "https://www.caireland.live/",
        remembered_urls=[
            "https://www.caireland.live/meeting-schedule",
            "https://www.caireland.live/find-a-meeting",
        ],
    )

    assert list(queue) == [
        ("https://www.caireland.live/meeting-schedule", -1),
        ("https://www.caireland.live/find-a-meeting", -1),
        ("https://www.caireland.live/", 0),
    ]


def test_crawler_skips_remembered_pages_for_japan_area_sources() -> None:
    source = Source(
        id="na-jp-kanto",
        fellowship="na",
        name="Kanto",
        url="https://najapan.org/meeting/kanto/",
        config={
            "scrape": {
                "successful_pages": [
                    {"url": "https://najapan.org/meeting/online-list/", "records_extracted": 28},
                    {"url": "https://najapan.org/meeting/kanto/mon/", "records_extracted": 12},
                ]
            }
        },
    )

    assert remembered_meeting_page_urls(source) == []


def test_crawler_reads_remembered_successful_pages_from_source_config() -> None:
    source = Source(
        id="ca-ie",
        fellowship="ca",
        name="CA Ireland",
        url="https://www.caireland.live/",
        config={
            "scrape": {
                "successful_pages": [
                    {"url": "https://www.caireland.live/meeting-schedule"},
                    {"url": "https://www.caireland.live/meeting-schedule"},
                    {"url": "https://www.caireland.live/groups"},
                ],
                "last_successful_page_url": "https://www.caireland.live/meeting-schedule",
            }
        },
    )

    assert remembered_meeting_page_urls(source) == [
        "https://www.caireland.live/meeting-schedule",
        "https://www.caireland.live/groups",
    ]


def test_crawler_reads_expected_records_for_remembered_page() -> None:
    source = Source(
        id="ca-ie",
        fellowship="ca",
        name="CA Ireland",
        url="https://www.caireland.live/",
        config={
            "scrape": {
                "successful_pages": [
                    {
                        "url": "https://www.caireland.live/meeting-schedule",
                        "records_extracted": 12,
                    },
                ],
                "last_successful_page_url": "https://www.caireland.live/groups",
                "last_successful_page_records": 4,
            }
        },
    )

    assert remembered_page_expected_records(
        source,
        "https://www.caireland.live/meeting-schedule#top",
    ) == 12
    assert remembered_page_expected_records(
        source,
        "https://www.caireland.live/groups",
    ) == 4


async def test_heuristic_interactions_can_skip_search_form_submission() -> None:
    class FakeLocator:
        @property
        def first(self) -> "FakeLocator":
            return self

        async def count(self) -> int:
            return 0

        async def is_visible(self, timeout: int) -> bool:
            return False

    class FakePage:
        search_form_queried = False

        def locator(self, selector: str) -> FakeLocator:
            if "input" in selector:
                self.search_form_queried = True
            return FakeLocator()

    page = FakePage()
    source = Source(id="na-wa", fellowship="na", name="Washington", url="https://example.org/")

    traces = await perform_heuristic_interactions(
        page,
        source,
        CrawlSettings(),
        allow_search_form=False,
    )

    assert traces == []
    assert not page.search_form_queried


def test_crawler_skips_search_form_when_directory_links_are_available() -> None:
    page_score = score_html(
        "https://www.na-ireland.org/na-meetings/",
        """
        <html>
          <title>NA Meetings</title>
          <body>
            <a href="/na-meetings/north/">Northern Area Meetings</a>
            <a href="/na-meetings/east/">Eastern Area Meetings</a>
          </body>
        </html>
        """,
    )
    links = prioritize_links(
        "https://www.na-ireland.org/na-meetings/",
        [
            {
                "url": "https://www.na-ireland.org/na-meetings/north/",
                "text": "Northern Area Meetings",
            },
            {
                "url": "https://www.na-ireland.org/?s=Ireland",
                "text": "Search",
            },
        ],
    )

    assert not should_allow_heuristic_search_form(
        "https://www.na-ireland.org/na-meetings/",
        page_score,
        links,
        requested=True,
    )


def test_crawler_stops_after_remembered_page_matches_previous_records() -> None:
    source = Source(
        id="ca-ie",
        fellowship="ca",
        name="CA Ireland",
        url="https://www.caireland.live/",
        config={
            "scrape": {
                "last_successful_page_url": "https://www.caireland.live/meeting-schedule",
                "last_successful_page_records": 4,
            }
        },
    )
    page = ScrapedPage(
        url="https://www.caireland.live/meeting-schedule",
        final_url="https://www.caireland.live/meeting-schedule",
        title="Meetings",
        html="",
        extracted=[
            ExtractedMeeting(
                payload={"name": "Monday Main"},
                method="test",
                confidence=0.9,
                source_page_url="https://www.caireland.live/meeting-schedule",
            )
            for _ in range(3)
        ],
    )

    assert should_stop_after_remembered_page(page, source)


def test_crawler_does_not_stop_after_remembered_page_large_drop() -> None:
    source = Source(
        id="ca-ie",
        fellowship="ca",
        name="CA Ireland",
        url="https://www.caireland.live/",
        config={
            "scrape": {
                "last_successful_page_url": "https://www.caireland.live/meeting-schedule",
                "last_successful_page_records": 20,
            }
        },
    )
    page = ScrapedPage(
        url="https://www.caireland.live/meeting-schedule",
        final_url="https://www.caireland.live/meeting-schedule",
        title="Meetings",
        html="",
        extracted=[
            ExtractedMeeting(
                payload={"name": "Only One"},
                method="test",
                confidence=0.9,
                source_page_url="https://www.caireland.live/meeting-schedule",
            )
        ],
    )

    assert not should_stop_after_remembered_page(page, source)


def test_crawler_does_not_stop_after_remembered_page_with_pending_remembered_url() -> None:
    source = Source(
        id="ca-ie",
        fellowship="ca",
        name="CA Ireland",
        url="https://www.caireland.live/",
    )
    page = ScrapedPage(
        url="https://www.caireland.live/meeting-schedule",
        final_url="https://www.caireland.live/meeting-schedule",
        title="Meetings",
        html="",
        extracted=[
            ExtractedMeeting(
                payload={"name": "Monday Main"},
                method="test",
                confidence=0.9,
                source_page_url="https://www.caireland.live/meeting-schedule",
            )
        ],
    )

    assert not should_stop_after_remembered_page(
        page,
        source,
        pending_queue=deque([("https://www.caireland.live/groups", -1)]),
    )


def test_crawler_can_fallback_to_common_meeting_paths() -> None:
    links = common_meeting_path_links("https://www.caireland.live/")
    urls = [link["url"] for link in links]

    assert "https://www.caireland.live/meeting-schedule" in urls
    assert "https://www.caireland.live/meetings/" in urls
    assert "https://www.caireland.live/groups/" in urls
    assert "https://www.caireland.live/meeting-locations" in urls
    assert "https://www.caireland.live/find-meeting/find-a-meeting" in urls
    assert "https://www.caireland.live/aa-groups/" in urls
    assert "https://www.caireland.live/meetings" not in urls


def test_crawler_stops_after_successful_meeting_directory() -> None:
    page = ScrapedPage(
        url="https://example.org/meetings",
        final_url="https://example.org/meetings",
        title="Meetings",
        html="",
        page_score=0.9,
        extracted=[
            ExtractedMeeting(
                payload={"name": "Monday Main"},
                method="test",
                confidence=0.9,
                source_page_url="https://example.org/meetings",
            )
            for _ in range(3)
        ],
    )

    assert should_stop_after_page(page, CrawlSettings())


def test_crawler_stops_after_record_rich_homepage() -> None:
    page = ScrapedPage(
        url="https://example.org/",
        final_url="https://example.org/",
        title="Homepage",
        html="",
        page_score=0.56,
        extracted=[
            ExtractedMeeting(
                payload={"name": "Homepage Meeting"},
                method="test",
                confidence=0.9,
                source_page_url="https://example.org/",
            )
            for _ in range(4)
        ],
    )

    assert should_stop_after_page(page, CrawlSettings())


def test_crawler_stops_after_any_landing_page_meeting() -> None:
    page = ScrapedPage(
        url="https://example.org/",
        final_url="https://example.org/",
        title="Homepage",
        html="",
        page_score=0.22,
        extracted=[
            ExtractedMeeting(
                payload={"name": "Only Homepage Meeting"},
                method="test",
                confidence=0.9,
                source_page_url="https://example.org/",
            )
        ],
    )

    assert should_stop_after_page(page, CrawlSettings())


def test_crawler_continues_after_landing_page_preview_with_directory_link() -> None:
    page = ScrapedPage(
        url="https://example.org/",
        final_url="https://example.org/",
        title="Homepage",
        html="",
        page_score=0.58,
        extracted=[
            ExtractedMeeting(
                payload={"name": "Homepage Preview"},
                method="test",
                confidence=0.9,
                source_page_url="https://example.org/",
            )
        ],
    )
    links = [
        {"url": "https://example.org/full-meetings/", "text": "Meetings"},
    ]

    assert not should_stop_after_page(page, CrawlSettings(), prioritized_links=links)
    assert _has_deeper_meeting_directory_link(page.final_url, links)


def test_crawler_ignores_landing_page_self_link_when_stopping() -> None:
    page = ScrapedPage(
        url="https://example.org/",
        final_url="https://example.org/",
        title="Homepage",
        html="",
        page_score=0.58,
        extracted=[
            ExtractedMeeting(
                payload={"name": "Homepage Schedule"},
                method="test",
                confidence=0.9,
                source_page_url="https://example.org/",
            )
        ],
    )
    links = [
        {"url": "https://example.org/", "text": "Meetings"},
    ]

    assert should_stop_after_page(page, CrawlSettings(), prioritized_links=links)


def test_crawler_continues_when_meeting_branch_siblings_are_pending() -> None:
    page = ScrapedPage(
        url="https://example.org/meetings/region-a/",
        final_url="https://example.org/meetings/region-a/",
        title="Region A Meetings",
        html="",
        page_score=0.6,
        extracted=[
            ExtractedMeeting(
                payload={"name": "Region A"},
                method="test",
                confidence=0.9,
                source_page_url="https://example.org/meetings/region-a/",
            )
            for _ in range(3)
        ],
    )
    pending = deque(
        [
            ("https://example.org/meetings/region-b/", 2),
            ("https://example.org/contact/", 1),
        ]
    )

    assert _has_pending_meeting_branch(page.final_url, pending)
    assert not should_stop_after_page(page, CrawlSettings(), pending_queue=pending)


def test_crawler_stops_after_empty_strong_meeting_directory() -> None:
    page = ScrapedPage(
        url="https://example.org/find-a-meeting",
        final_url="https://example.org/find-a-meeting",
        title="Find a Meeting",
        html="",
        page_score=0.9,
        page_signals=["strong_public_meeting_directory", "meeting_form"],
        extracted=[],
    )

    assert should_stop_after_empty_meeting_directory(page, CrawlSettings())


def test_crawler_does_not_stop_empty_landing_page() -> None:
    page = ScrapedPage(
        url="https://example.org/",
        final_url="https://example.org/",
        title="Home",
        html="",
        page_score=0.9,
        page_signals=["meeting_form"],
        extracted=[],
    )

    assert not should_stop_after_empty_meeting_directory(page, CrawlSettings())


def test_crawler_prunes_guessed_common_paths_after_not_found_pages() -> None:
    queue = deque(
        [
            ("https://example.org/meeting-schedule", 1),
            ("https://example.org/find-a-meeting", 1),
            ("https://example.org/contact", 1),
        ]
    )
    page = ScrapedPage(
        url="https://example.org/meetings/",
        final_url="https://example.org/meetings",
        title="404 Error: Page Not Found",
        html="",
    )

    pruned = _without_common_meeting_path_links(queue, "https://example.org/")

    assert _looks_like_not_found_page(page)
    assert is_common_meeting_path("https://example.org/", "https://example.org/meetings")
    assert list(pruned) == [("https://example.org/contact", 1)]


def test_crawler_treats_group_paths_as_common_meeting_paths() -> None:
    assert is_common_meeting_path("https://example.org/", "https://example.org/groups")
    assert is_common_meeting_path("https://example.org/", "https://example.org/aa-groups")

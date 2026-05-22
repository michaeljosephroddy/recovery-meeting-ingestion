import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.adapters.html_config import configured_selectors, extract_records_from_html
from app.scraping.meeting_page_detector import score_html
from app.scraping.meeting_vocabulary import DAY_RE
from app.scraping.models import ExtractedMeeting
from app.scraping.scoring import confidence_for_payload

TIME_RE = re.compile(
    r"\b(?:(?:\d{1,2}(?::|\.|;)?\d{2}|\d{1,2})\s*(?:am|pm|a\.m\.|p\.m\.)|"
    r"kl\.?\s*(?:[01]?\d|2[0-3])(?:(?::|\.)[0-5]\d)?"
    r"(?:\s*(?:to|-|–|—)\s*(?:[01]?\d|2[0-3])(?:(?::|\.)[0-5]\d)?)?|"
    r"(?:[01]?\d|2[0-3]):[0-5]\d"
    r"(?:\s*(?:to|-|–|—)\s*(?:[01]?\d|2[0-3]):[0-5]\d)?|"
    r"12\s*noon|midnight)"
    r"(?=\W|$)",
    re.IGNORECASE,
)
TIME_RANGE_TRAILING_MARKER_RE = re.compile(
    r"\b(?P<start>\d{1,2}(?::|\.|;)\d{2})\s*(?:to|-|–|—)\s*"
    r"\d{1,2}(?::|\.|;)\d{2}\s*(?P<marker>am|pm|a\.m\.|p\.m\.)\b",
    re.IGNORECASE,
)
ADDRESS_RE = re.compile(
    r"\b(?:\d{1,6}(?:st|nd|rd|th)?\s+[A-Za-z0-9'.\s-]{1,60}"
    r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|boulevard|blvd\.?|drive|dr\.?|"
    r"lane|ln\.?|way|court|ct\.?|place|pl\.?|parkway|pkwy\.?)|"
    r"[A-Za-z0-9'.-]+\s+"
    r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|boulevard|blvd\.?|drive|dr\.?|lane|"
    r"ln\.?|way|court|ct\.?|place|pl\.?|parkway|pkwy\.?|"
    r"church|hall|center|centre|club|school|library|hospital))\b",
    re.IGNORECASE,
)
NON_MEETING_URL_RE = re.compile(
    r"(?:apps\.apple\.com|play\.google\.com|facebook\.com|instagram\.com|youtube\.com|"
    r"youtu\.be|twitter\.com|x\.com|linkedin\.com|maps\.google|paypal\.com|donate|"
    r"/event/|/events/|/news/|/blog/)",
    re.IGNORECASE,
)
ONLINE_MEETING_URL_RE = re.compile(
    r"(?:zoom\.|teams\.microsoft\.com|meet\.google\.com|webex\.com|jitsi|gotomeet|"
    r"bluejeans)",
    re.IGNORECASE,
)
HEADER_MAP = {
    "name": {"meeting", "meeting name", "group", "group name", "name"},
    "day": {"day", "weekday", "dia", "día", "jour"},
    "time": {"time", "start", "start time", "hora", "horário", "horario", "heure"},
    "venue_name": {"venue", "location", "place"},
    "address_line1": {"address", "street"},
    "city": {"city", "town"},
    "formats": {"type", "types", "format", "formats"},
    "notes": {"notes", "details"},
    "online_url": {"online", "url", "link", "zoom"},
}
TEXT_STRIP_CHARS = " -|–—\u00a0"
DAY_INDEX_NAMES = {
    0: "Sunday",
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
}


def extract_meetings_from_html(
    html: str,
    *,
    source_page_url: str,
    source_config: dict[str, Any] | None = None,
) -> list[ExtractedMeeting]:
    config = source_config or {}
    page_score = score_html(source_page_url, html).score
    extracted: list[ExtractedMeeting] = []

    if config.get("selectors"):
        extracted.extend(_extract_configured(html, config, source_page_url, page_score))
    if extracted:
        return extracted

    extracted.extend(_extract_tsml_json(html, source_page_url, page_score))
    if extracted:
        return _dedupe_extracted(extracted)

    soup = BeautifulSoup(html, "html.parser")
    extracted.extend(_extract_tsml_tables(soup, source_page_url, page_score))
    extracted.extend(_extract_bmlt_tables(soup, source_page_url, page_score))
    extracted.extend(_extract_tables(soup, source_page_url, page_score))
    extracted.extend(_extract_cards(soup, source_page_url, page_score))
    extracted.extend(_extract_day_sections(soup, source_page_url, page_score))
    if not extracted:
        extracted.extend(_extract_direct_listing_blocks(soup, source_page_url, page_score))
    if not extracted:
        extracted.extend(_extract_inline_schedule_lines(soup, source_page_url, page_score))
    if not extracted:
        extracted.extend(_extract_structured_text_meetings(soup, source_page_url, page_score))
    if not extracted:
        extracted.extend(_extract_sequenced_text_meetings(soup, source_page_url, page_score))
    if not extracted:
        extracted.extend(_extract_text_blocks(soup, source_page_url, page_score))
    return _dedupe_extracted(extracted)


def _extract_configured(
    html: str,
    config: dict[str, Any],
    source_page_url: str,
    page_score: float,
) -> list[ExtractedMeeting]:
    selectors = configured_selectors(config)
    payloads = extract_records_from_html(html, selectors)
    meetings: list[ExtractedMeeting] = []
    for payload in payloads:
        confidence, signals = confidence_for_payload(
            payload,
            method="configured_selectors",
            page_score=page_score,
            repeated_structure=True,
        )
        meetings.append(
            ExtractedMeeting(
                payload=payload,
                method="configured_selectors",
                confidence=max(confidence, 0.78),
                source_page_url=source_page_url,
                signals=signals,
                selector_hint=str(selectors["row"]),
            )
        )
    return meetings


def _extract_tsml_json(
    html: str,
    source_page_url: str,
    page_score: float,
) -> list[ExtractedMeeting]:
    raw_text = html.strip()
    if not raw_text.startswith(("[", "{")):
        soup = BeautifulSoup(html, "html.parser")
        pre = soup.select_one("pre")
        raw_text = pre.get_text("", strip=True) if pre else ""
    if not raw_text.startswith(("[", "{")):
        return []
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return []
    records = parsed if isinstance(parsed, list) else parsed.get("meetings")
    if not isinstance(records, list):
        return []

    meetings: list[ExtractedMeeting] = []
    for row_index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        payload = _payload_from_tsml_record(record)
        payload = _without_empty(payload)
        if not _looks_like_meeting_payload(payload):
            continue
        confidence, signals = confidence_for_payload(
            payload,
            method="tsml_json_feed",
            page_score=max(page_score, 0.9),
            repeated_structure=True,
        )
        meetings.append(
            ExtractedMeeting(
                payload={**payload, "row_index": row_index},
                method="tsml_json_feed",
                confidence=max(confidence, 0.86),
                source_page_url=source_page_url,
                signals=signals,
                selector_hint="tsml_json",
            )
        )
    return meetings


def _payload_from_tsml_record(record: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if source_record_id := _optional_text(record.get("id") or record.get("slug")):
        payload["source_record_id"] = source_record_id
    if name := _optional_text(record.get("name")):
        payload["name"] = name
    if day := _day_name_from_index(record.get("day")):
        payload["day"] = day
    if time := _optional_text(record.get("time_formatted") or record.get("time")):
        payload["time"] = _normalize_extracted_time(time)
    if venue := _optional_text(record.get("location")):
        payload["venue_name"] = venue
    if address := _optional_text(record.get("formatted_address") or record.get("address")):
        payload["address_line1"] = address
    if city := _optional_text(record.get("city")):
        payload["city"] = city
    if region := _optional_text(record.get("region")):
        payload["region"] = region
    if timezone := _optional_text(record.get("timezone")):
        payload["timezone"] = timezone
    if latitude := _optional_text(record.get("latitude")):
        payload["latitude"] = latitude
    if longitude := _optional_text(record.get("longitude")):
        payload["longitude"] = longitude
    if online_url := _optional_text(record.get("conference_url")):
        payload["online_url"] = online_url
    notes = [
        value
        for value in (
            _optional_text(record.get("conference_url_notes")),
            _optional_text(record.get("notes")),
        )
        if value
    ]
    if notes:
        payload["phone_join_info"] = " ".join(notes)
    if types := record.get("types"):
        payload["formats"] = ", ".join(str(item).strip() for item in types if str(item).strip())
    if attendance := _optional_text(record.get("attendance_option")):
        payload["attendance_option"] = attendance.replace("_", " ")
    return payload


def _extract_tsml_tables(
    soup: BeautifulSoup,
    source_page_url: str,
    page_score: float,
) -> list[ExtractedMeeting]:
    meetings: list[ExtractedMeeting] = []
    for table_index, table in enumerate(soup.select("table")):
        if not table.select_one("tbody#meetings_tbody, tr[class*='attendance-']"):
            continue
        for row_index, row in enumerate(table.select("tbody tr")):
            if not isinstance(row, Tag):
                continue
            payload = _payload_from_tsml_table_row(row, source_page_url)
            payload = _without_empty(payload)
            if not _looks_like_meeting_payload(payload):
                continue
            confidence, signals = confidence_for_payload(
                payload,
                method="tsml_rendered_table_row",
                page_score=page_score,
                repeated_structure=True,
                table_headers=True,
            )
            meetings.append(
                ExtractedMeeting(
                    payload={**payload, "row_index": row_index},
                    method="tsml_rendered_table_row",
                    confidence=max(confidence, 0.82),
                    source_page_url=source_page_url,
                    signals=signals,
                    selector_hint=f"table:nth-of-type({table_index + 1}) tr",
                )
            )
    return meetings


def _payload_from_tsml_table_row(row: Tag, source_page_url: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    time_cell = row.select_one("td.time")
    if time_cell is not None:
        sort_value = str(time_cell.get("data-sort") or "")
        if day := _day_name_from_tsml_sort(sort_value):
            payload["day"] = day
        time_text = _clean_text(time_cell)
        if time := _first_time_match(time_text) or _time_from_tsml_sort(sort_value):
            payload["time"] = _normalize_extracted_time(time)

    name_cell = row.select_one("td.name")
    if name_cell is not None:
        if name := _clean_text(name_cell):
            payload["name"] = name
        link = name_cell.select_one("a[href]")
        if link and (href := link.get("href")):
            meeting_url = urljoin(source_page_url, str(href))
            if source_record_id := _source_record_id_from_meeting_url(meeting_url):
                payload["source_record_id"] = source_record_id

    location_cell = row.select_one("td.location, td.location_group")
    if location_cell is not None:
        if location := _first_text(location_cell, ".location-name"):
            payload["venue_name"] = location
        if attendance := _tsml_attendance_option(row, location_cell):
            payload["attendance_option"] = attendance

    if (address_cell := row.select_one("td.address")) and (address := _clean_text(address_cell)):
        payload["address_line1"] = address
    if (region_cell := row.select_one("td.region")) and (region := _clean_text(region_cell)):
        payload["region"] = region
    if (types_cell := row.select_one("td.types")) and (types := _clean_text(types_cell)):
        payload["formats"] = types
    return payload


def _extract_tables(
    soup: BeautifulSoup,
    source_page_url: str,
    page_score: float,
) -> list[ExtractedMeeting]:
    meetings: list[ExtractedMeeting] = []
    for table_index, table in enumerate(soup.select("table")):
        headers = [_clean_text(cell) for cell in table.select("tr th")]
        if not headers:
            first_row = table.select_one("tr")
            headers = [_clean_text(cell) for cell in first_row.select("td")] if first_row else []
        field_map = _field_map_for_headers(headers)
        if len(field_map) < 2:
            continue
        rows = table.select("tbody tr") or table.select("tr")[1:]
        for row_index, row in enumerate(rows):
            cells = row.select("td")
            if len(cells) < 2:
                continue
            payload = {
                field: _cell_value(cells[column_index], source_page_url, field)
                for column_index, field in field_map.items()
                if column_index < len(cells)
            }
            payload = _enrich_table_payload(payload)
            payload = _without_empty(payload)
            if not _looks_like_meeting_payload(payload):
                continue
            confidence, signals = confidence_for_payload(
                payload,
                method="heuristic_table_row",
                page_score=page_score,
                repeated_structure=True,
                table_headers=True,
            )
            meetings.append(
                ExtractedMeeting(
                    payload={**payload, "row_index": row_index},
                    method="heuristic_table_row",
                    confidence=confidence,
                    source_page_url=source_page_url,
                    signals=signals,
                    selector_hint=f"table:nth-of-type({table_index + 1}) tr",
                )
            )
    return meetings


def _extract_bmlt_tables(
    soup: BeautifulSoup,
    source_page_url: str,
    page_score: float,
) -> list[ExtractedMeeting]:
    meetings: list[ExtractedMeeting] = []
    for table_index, table in enumerate(soup.select("table.bmlt-table")):
        for row_index, row in enumerate(table.select("tr.bmlt-data-row")):
            cells = row.select("td")
            if len(cells) < 2:
                continue
            payload: dict[str, Any] = {}
            source_record_id = str(row.get("id") or "").removeprefix("meeting-data-row-")
            if source_record_id:
                payload["source_record_id"] = source_record_id
            if day := _first_text(cells[0], ".bmlt-day"):
                payload["day"] = day
            else:
                time_cell_text = _clean_text(cells[0])
                if day := _first_match(DAY_RE, time_cell_text):
                    payload["day"] = day
            if time_text := _first_text(cells[0], ".bmlt-time-2, .bmlt-time"):
                start_time = time_text.split("-", 1)[0].strip()
                if time := _first_time_match(start_time):
                    payload["time"] = _normalize_extracted_time(time)
            elif time := _first_time_match(_clean_text(cells[0])):
                payload["time"] = _normalize_extracted_time(time)
            if formats := str(row.get("data-formats") or "").replace("-", " ").strip():
                payload["formats"] = formats

            detail_cell = cells[1]
            if name := _first_text(detail_cell, ".meeting-name"):
                payload["name"] = name
            if venue := _first_text(detail_cell, ".location-text"):
                payload["venue_name"] = venue
            if address := _first_text(detail_cell, ".meeting-address"):
                payload["address_line1"] = address
            if info := _first_text(detail_cell, ".location-information"):
                payload["notes"] = info
            online_link = detail_cell.select_one(
                ".virtual-meeting-link a[href], [class*='virtual-meeting-link'] a[href]"
            )
            if (
                online_link
                and (href := online_link.get("href"))
                and (online_url := _meeting_url_or_none(urljoin(source_page_url, str(href))))
            ):
                payload["online_url"] = online_url
            geo = _first_text(row, ".geo")
            if geo and "," in geo:
                latitude, longitude = [part.strip() for part in geo.split(",", 1)]
                payload["latitude"] = latitude
                payload["longitude"] = longitude

            payload = _without_empty(payload)
            if not _looks_like_meeting_payload(payload):
                continue
            confidence, signals = confidence_for_payload(
                payload,
                method="bmlt_rendered_table_row",
                page_score=page_score,
                repeated_structure=True,
                table_headers=True,
            )
            meetings.append(
                ExtractedMeeting(
                    payload={**payload, "row_index": row_index},
                    method="bmlt_rendered_table_row",
                    confidence=max(confidence, 0.82),
                    source_page_url=source_page_url,
                    signals=signals,
                    selector_hint=f"table.bmlt-table:nth-of-type({table_index + 1}) tr",
                )
            )
    return meetings


def _extract_cards(
    soup: BeautifulSoup,
    source_page_url: str,
    page_score: float,
) -> list[ExtractedMeeting]:
    meetings: list[ExtractedMeeting] = []
    for selector in (
        "li",
        "article",
        ".meeting",
        ".meeting-card",
        ".event-card",
        "div[data-ux='ContentBasic']",
    ):
        for index, tag in enumerate(soup.select(selector)):
            if not isinstance(tag, Tag):
                continue
            if selector == "article" and tag.select_one(".entry-content"):
                continue
            text = tag.get_text("\n", strip=True)
            if len(text) > 800 or not (DAY_RE.search(text) and TIME_RE.search(text)):
                continue
            payload = _payload_from_text(text)
            link = tag.select_one("a[href]")
            if link and (href := link.get("href")):
                online_url = _meeting_url_or_none(urljoin(source_page_url, str(href)))
                if online_url:
                    payload.setdefault("online_url", online_url)
            name = _first_text(tag, ".name, .meeting-name, h2, h3, h4, strong")
            if name:
                payload["name"] = name
            address = _first_text(tag, ".address, .location, .venue")
            if address:
                payload["address_line1"] = address
            payload = _without_empty(payload)
            if not _looks_like_meeting_payload(payload):
                continue
            confidence, signals = confidence_for_payload(
                payload,
                method="heuristic_card",
                page_score=page_score,
                repeated_structure=True,
            )
            meetings.append(
                ExtractedMeeting(
                    payload={**payload, "row_index": index},
                    method="heuristic_card",
                    confidence=confidence,
                    source_page_url=source_page_url,
                    signals=signals,
                    selector_hint=selector,
                )
            )
    return meetings


def _extract_day_sections(
    soup: BeautifulSoup,
    source_page_url: str,
    page_score: float,
) -> list[ExtractedMeeting]:
    meetings: list[ExtractedMeeting] = []
    containers = soup.select(".entry-content, article, main, .panel")
    for container_index, container in enumerate(containers):
        lines = _day_section_lines(container)
        if not lines:
            continue
        current_day = _day_from_title(container) or _day_from_title(soup)
        pending: dict[str, Any] | None = None
        pending_name: str | None = None
        row_index = 0
        for line in lines:
            day_heading = _day_heading_or_none(line)
            if day_heading:
                if pending is not None:
                    _append_pending_day_section(
                        meetings, pending, source_page_url, page_score, container_index, row_index
                    )
                    row_index += 1
                    pending = None
                pending_name = None
                current_day = day_heading
                continue
            time = _first_time_match(line)
            if time and current_day:
                if pending is not None:
                    _append_pending_day_section(
                        meetings, pending, source_page_url, page_score, container_index, row_index
                    )
                    row_index += 1
                pending = {"day": current_day, "time": _normalize_extracted_time(time)}
                if pending_name:
                    pending["name"] = pending_name
                    pending_name = None
                _merge_time_line_remainder(pending, line, time)
                continue
            if (
                pending is not None
                and pending.get("name")
                and _looks_like_next_meeting_name(line)
            ):
                _append_pending_day_section(
                    meetings, pending, source_page_url, page_score, container_index, row_index
                )
                row_index += 1
                pending = None
                pending_name = _clean_meeting_name_line(line)
                continue
            if pending is not None:
                _merge_day_section_line(pending, line)
                continue
            if not pending_name and _looks_like_next_meeting_name(line):
                pending_name = _clean_meeting_name_line(line)
        if pending is not None:
            _append_pending_day_section(
                meetings, pending, source_page_url, page_score, container_index, row_index
            )
    return meetings


def _extract_inline_schedule_lines(
    soup: BeautifulSoup,
    source_page_url: str,
    page_score: float,
) -> list[ExtractedMeeting]:
    meetings: list[ExtractedMeeting] = []
    containers = soup.select(".entry-content, article, main") or [soup]
    row_index = 0
    for container_index, container in enumerate(containers):
        for line in _day_section_lines(container):
            if len(line) > 500 or not (DAY_RE.search(line) and TIME_RE.search(line)):
                continue
            payloads = _payloads_from_inline_schedule_line(line)
            repeated_structure = len(payloads) > 1
            for payload in payloads:
                payload = _without_empty(payload)
                if not _looks_like_meeting_payload(payload):
                    continue
                confidence, signals = confidence_for_payload(
                    payload,
                    method="heuristic_inline_schedule",
                    page_score=page_score,
                    repeated_structure=repeated_structure,
                )
                meetings.append(
                    ExtractedMeeting(
                        payload={**payload, "row_index": row_index},
                        method="heuristic_inline_schedule",
                        confidence=confidence,
                        source_page_url=source_page_url,
                        signals=signals,
                        selector_hint=f"inline_schedule:{container_index}",
                    )
                )
                row_index += 1
    return meetings


def _payloads_from_inline_schedule_line(line: str) -> list[dict[str, str]]:
    day_matches = list(DAY_RE.finditer(line))
    if not day_matches:
        return []
    first_day = day_matches[0]
    name = _clean_meeting_name_line(line[: first_day.start()])
    if not name:
        return []
    payloads: list[dict[str, str]] = []
    last_time_end: int | None = None
    for index, day_match in enumerate(day_matches):
        next_day_start = (
            day_matches[index + 1].start()
            if index + 1 < len(day_matches)
            else len(line)
        )
        segment = line[day_match.end() : next_day_start]
        time = _first_time_match(segment)
        if not time:
            continue
        absolute_time_end = day_match.end() + segment.find(time) + len(time)
        last_time_end = (
            absolute_time_end
            if last_time_end is None
            else max(last_time_end, absolute_time_end)
        )
        payloads.append(
            {
                "name": name,
                "day": _day_from_schedule_line(day_match.group(0)) or day_match.group(0).title(),
                "time": _normalize_extracted_time(time),
            }
        )
    if not payloads or last_time_end is None:
        return []
    tail = _clean_inline_schedule_tail(line[last_time_end:])
    if tail:
        for payload in payloads:
            for detail in _inline_schedule_detail_lines(tail):
                _merge_day_section_line(payload, detail)
    return payloads


def _clean_inline_schedule_tail(text: str) -> str:
    cleaned = re.sub(r"^\s*\([^)]*\)\s*", "", text).strip(TEXT_STRIP_CHARS)
    cleaned = re.sub(r"\bse kart nederst\b", "", cleaned, flags=re.IGNORECASE)
    return _clean_fragment(cleaned)


def _inline_schedule_detail_lines(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\s+(?=https?://)", text) if part.strip()]
    return parts or [text]


def _extract_text_blocks(
    soup: BeautifulSoup,
    source_page_url: str,
    page_score: float,
) -> list[ExtractedMeeting]:
    text = soup.get_text("\n", strip=True)
    blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
    meetings: list[ExtractedMeeting] = []
    for index, block in enumerate(blocks):
        if len(block) > 900:
            continue
        if not (DAY_RE.search(block) and TIME_RE.search(block)):
            continue
        payload = _payload_from_text(block)
        payload = _without_empty(payload)
        if not (
            payload.get("address_line1")
            or payload.get("venue_name")
            or payload.get("online_url")
            or payload.get("phone_join_info")
        ):
            continue
        if not _looks_like_meeting_payload(payload):
            continue
        confidence, signals = confidence_for_payload(
            payload,
            method="heuristic_text_block",
            page_score=page_score,
        )
        meetings.append(
            ExtractedMeeting(
                payload={**payload, "row_index": index},
                method="heuristic_text_block",
                confidence=confidence,
                source_page_url=source_page_url,
                signals=signals,
                selector_hint="text_block",
            )
        )
    return meetings


def _extract_structured_text_meetings(
    soup: BeautifulSoup,
    source_page_url: str,
    page_score: float,
) -> list[ExtractedMeeting]:
    lines = [_clean_fragment(line) for line in soup.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line and line != "\u200b"]
    if "Number found:" not in lines:
        return []
    meetings: list[ExtractedMeeting] = []
    start_index = _structured_text_start_index(lines)
    index = start_index
    row_index = 0
    while index < len(lines) - 2:
        if not _is_structured_text_meeting_start(lines, index):
            index += 1
            continue
        next_index = _next_structured_text_meeting_index(lines, index + 3)
        payload = _payload_from_structured_text_block(lines[index:next_index])
        payload = _without_empty(payload)
        if _looks_like_meeting_payload(payload):
            confidence, signals = confidence_for_payload(
                payload,
                method="heuristic_structured_text_list",
                page_score=page_score,
                repeated_structure=True,
            )
            meetings.append(
                ExtractedMeeting(
                    payload={**payload, "row_index": row_index},
                    method="heuristic_structured_text_list",
                    confidence=confidence,
                    source_page_url=source_page_url,
                    signals=signals,
                    selector_hint="structured_text_list",
                )
            )
            row_index += 1
        index = max(next_index, index + 1)
    return meetings


def _extract_sequenced_text_meetings(
    soup: BeautifulSoup,
    source_page_url: str,
    page_score: float,
) -> list[ExtractedMeeting]:
    if soup.select_one("[data-rendered-text-fallback]") is None:
        return []
    lines = [_clean_fragment(line) for line in soup.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line and line != "\u200b"]
    meetings: list[ExtractedMeeting] = []
    row_index = 0
    for index, line in enumerate(lines):
        day = _day_from_schedule_line(line)
        time = _first_time_match(line)
        if not day or not time:
            continue
        name = _previous_sequence_name(lines, index)
        if not name:
            continue
        payload: dict[str, Any] = {
            "name": name,
            "day": day,
            "time": _normalize_extracted_time(time),
        }
        for detail in _sequence_detail_lines(lines, index + 1):
            _merge_sequence_detail_line(payload, detail)
        payload = _without_empty(payload)
        if not _looks_like_meeting_payload(payload):
            continue
        confidence, signals = confidence_for_payload(
            payload,
            method="heuristic_sequence_text",
            page_score=page_score,
            repeated_structure=True,
        )
        meetings.append(
            ExtractedMeeting(
                payload={**payload, "row_index": row_index},
                method="heuristic_sequence_text",
                confidence=confidence,
                source_page_url=source_page_url,
                signals=signals,
                selector_hint="sequence_text",
            )
        )
        row_index += 1
    return meetings


def _extract_direct_listing_blocks(
    soup: BeautifulSoup,
    source_page_url: str,
    page_score: float,
) -> list[ExtractedMeeting]:
    meetings: list[ExtractedMeeting] = []
    containers = soup.select(".entry-content, article, main") or [soup]
    for container_index, container in enumerate(containers):
        section_name: str | None = None
        pending_day_payload: dict[str, str] | None = None
        for row_index, paragraph in enumerate(container.select("p")):
            text = _clean_text(paragraph)
            if not text:
                continue
            has_day = bool(DAY_RE.search(text))
            has_time = bool(TIME_RE.search(text))
            if pending_day_payload and has_time and not has_day:
                payload = _payload_from_direct_listing_paragraph(
                    paragraph,
                    pending_day_payload.get("name") or section_name,
                    source_page_url,
                )
                payload["day"] = pending_day_payload["day"]
                for detail in _direct_listing_following_detail_lines(paragraph):
                    _merge_direct_listing_line(payload, detail)
                pending_day_payload = None
                payload = _without_empty(payload)
                if not _looks_like_meeting_payload(payload):
                    continue
                confidence, signals = confidence_for_payload(
                    payload,
                    method="heuristic_direct_listing",
                    page_score=page_score,
                    repeated_structure=True,
                )
                meetings.append(
                    ExtractedMeeting(
                        payload={**payload, "row_index": row_index},
                        method="heuristic_direct_listing",
                        confidence=confidence,
                        source_page_url=source_page_url,
                        signals=signals,
                        selector_hint=f"direct_listing:{container_index}",
                    )
                )
                continue
            if not (has_day and has_time):
                if has_day and (day := _day_from_schedule_line(text)):
                    pending_day_payload = {
                        "day": day,
                        "name": _direct_listing_name(paragraph, section_name)
                        or _clean_meeting_name_line(text)
                        or "",
                    }
                    continue
                section_name = _direct_listing_section_name(paragraph) or section_name
                continue
            payload = _payload_from_direct_listing_paragraph(
                paragraph,
                section_name,
                source_page_url,
            )
            for detail in _direct_listing_following_detail_lines(paragraph):
                _merge_direct_listing_line(payload, detail)
            payload = _without_empty(payload)
            if not _looks_like_meeting_payload(payload):
                continue
            confidence, signals = confidence_for_payload(
                payload,
                method="heuristic_direct_listing",
                page_score=page_score,
                repeated_structure=True,
            )
            meetings.append(
                ExtractedMeeting(
                    payload={**payload, "row_index": row_index},
                    method="heuristic_direct_listing",
                    confidence=confidence,
                    source_page_url=source_page_url,
                    signals=signals,
                    selector_hint=f"direct_listing:{container_index}",
                )
            )
    return meetings


def _field_map_for_headers(headers: list[str]) -> dict[int, str]:
    field_map: dict[int, str] = {}
    used_fields: set[str] = set()
    for index, header in enumerate(headers):
        lowered = header.lower().strip()
        for field, aliases in HEADER_MAP.items():
            if field in used_fields:
                continue
            if lowered in aliases or any(alias in lowered for alias in aliases):
                field_map[index] = field
                used_fields.add(field)
                break
    return field_map


def _cell_value(cell: Tag, source_page_url: str, field: str) -> str | None:
    if field == "online_url":
        link = cell.select_one("a[href]")
        if link and (href := link.get("href")):
            return urljoin(source_page_url, str(href))
    return _clean_text(cell) or None


def _enrich_table_payload(payload: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(payload)
    time_value = str(enriched.get("time") or "")
    if time_value:
        if not enriched.get("day") and (day := _first_match(DAY_RE, time_value)):
            enriched["day"] = day
        if time := _first_time_match(time_value):
            enriched["time"] = _normalize_extracted_time(time)
    address = str(enriched.get("address_line1") or "").strip()
    if address.lower() in {"zoom", "zoom meeting", "phone", "telephone", "online"}:
        enriched.pop("address_line1", None)
        enriched["phone_join_info"] = address
    elif "zoom" in address.lower() and not enriched.get("phone_join_info"):
        enriched["phone_join_info"] = "Zoom"
    return enriched


def _payload_from_text(text: str) -> dict[str, str]:
    lines = [_clean_fragment(line) for line in text.splitlines() if _clean_fragment(line)]
    if len(lines) <= 1:
        lines = [
            _clean_fragment(part)
            for part in re.split(r"\s{2,}|\s+[|]\s+", text)
            if _clean_fragment(part)
        ]
    day = _first_match(DAY_RE, text)
    time = _first_time_match(text)
    payload: dict[str, str] = {}
    if day:
        payload["day"] = day
    if time:
        payload["time"] = _normalize_extracted_time(time)
    if lines:
        name = next((line for line in lines if line != day and line != time), None)
        if name:
            payload["name"] = name
    address_lines = [
        line
        for line in lines
        if ADDRESS_RE.search(line) and not (DAY_RE.search(line) and TIME_RE.search(line))
    ]
    address = next((line for line in address_lines if any(char.isdigit() for char in line)), None)
    address = address or next(iter(address_lines), None)
    if address:
        payload["address_line1"] = address
    online = next(
        (
            url
            for line in lines
            if line.startswith(("http://", "https://"))
            if (url := _meeting_url_or_none(line)) is not None
        ),
        None,
    )
    if online:
        payload["online_url"] = online
    return payload


def _payload_from_direct_listing_paragraph(
    paragraph: Tag,
    section_name: str | None,
    source_page_url: str,
) -> dict[str, str]:
    text = paragraph.get_text("\n", strip=True)
    day = _first_match(DAY_RE, text)
    time = _first_time_match(text)
    payload: dict[str, str] = {}
    if day:
        payload["day"] = day
    if time:
        payload["time"] = _normalize_extracted_time(time)
    if name := _direct_listing_name(paragraph, section_name):
        payload["name"] = name

    for line in (_clean_fragment(part) for part in text.splitlines()):
        if not line:
            continue
        if time and TIME_RE.search(line):
            remainder = _clean_direct_listing_time_remainder(line, time)
            if remainder:
                _merge_direct_listing_line(payload, remainder)
            continue
        _merge_direct_listing_line(payload, line)

    for link in paragraph.select("a[href]"):
        href = str(link.get("href") or "")
        if not href:
            continue
        absolute_url = urljoin(source_page_url, href)
        if online_url := _meeting_url_or_none(absolute_url):
            payload.setdefault("online_url", online_url)
            continue
        link_text = _clean_text(link)
        if link_text and _looks_like_address_fallback(link_text):
            payload.setdefault("address_line1", link_text)

    return payload


def _direct_listing_following_detail_lines(paragraph: Tag) -> list[str]:
    details: list[str] = []
    for sibling in paragraph.find_next_siblings():
        if not isinstance(sibling, Tag):
            continue
        if sibling.name != "p":
            break
        text = _clean_text(sibling)
        if not text:
            continue
        if _direct_listing_starts_new_schedule(text):
            break
        details.extend(
            line
            for line in (
                _clean_fragment(part) for part in sibling.get_text("\n", strip=True).splitlines()
            )
            if line and not _is_non_meeting_detail_line(line)
        )
    return details


def _direct_listing_starts_new_schedule(text: str) -> bool:
    if not DAY_RE.search(text):
        return False
    if TIME_RE.search(text):
        return True
    return len(text.split()) <= 5 and len(text) <= 80


def _payload_from_structured_text_block(lines: list[str]) -> dict[str, str]:
    payload: dict[str, str] = {
        "name": lines[0],
        "day": _structured_text_day(lines[1]),
        "time": _normalize_extracted_time(lines[2]),
    }
    if len(lines) > 3 and lines[3].lower() in {"online", "in-person", "in person", "hybrid"}:
        payload["attendance_option"] = lines[3]
    if len(lines) > 4 and not _is_placeholder_line(lines[4]):
        payload["city"] = lines[4]

    detail_lines = [line for line in lines[5:] if not _is_placeholder_line(line)]
    connection_lines: list[str] = []
    for line in detail_lines:
        lowered = line.lower()
        if lowered.startswith("attendance is limited"):
            break
        if _is_connection_line(line):
            connection_lines.append(line)
            continue
        if not payload.get("formats") and "meeting" in lowered:
            payload["formats"] = line
            continue
        if not payload.get("address_line1") and _looks_like_address_fallback(line):
            payload["address_line1"] = line
            continue
        if not payload.get("venue_name") and not _is_instruction_line(line):
            payload["venue_name"] = line
    if connection_lines:
        payload["phone_join_info"] = " ".join(connection_lines)
    return payload


def _day_section_lines(container: Tag) -> list[str]:
    lines: list[str] = []
    for node in container.select("h1, h2, h3, h4, p, li"):
        cleaned = _clean_fragment(_clean_text(node))
        if cleaned:
            lines.append(cleaned)
    return lines


def _day_from_title(container: Tag | BeautifulSoup) -> str | None:
    title = container.select_one("h1, h2, h3, title, .panel-title, .wb-accordion-title")
    if title is None:
        return None
    return _day_heading_or_none(_clean_text(title))


def _day_heading_or_none(text: str) -> str | None:
    cleaned = _clean_fragment(text)
    if len(cleaned) > 32 or TIME_RE.search(cleaned):
        return None
    lowered = cleaned.lower()
    match = DAY_RE.fullmatch(lowered)
    if match is None and lowered.endswith("s"):
        match = DAY_RE.fullmatch(lowered.removesuffix("s"))
    if match:
        return match.group(0).title()
    return None


def _merge_time_line_remainder(payload: dict[str, Any], line: str, time: str) -> None:
    remainder = _clean_fragment(line.replace(time, "", 1))
    remainder = _clean_schedule_remainder(remainder)
    if not remainder:
        return
    if _looks_like_format_text(remainder):
        payload["formats"] = remainder
        return
    _merge_day_section_line(payload, remainder)


def _merge_day_section_line(payload: dict[str, Any], line: str) -> None:
    line = _clean_fragment(line)
    if not line:
        return
    if _is_timezone_only_line(line):
        return
    lowered = line.lower()
    if (url := _first_url(line)) and (online_url := _meeting_url_or_none(url)):
        payload.setdefault("online_url", online_url)
    if (
        "zoom" in lowered
        or "meeting id" in lowered
        or "passcode" in lowered
        or "hasło" in lowered
        or lowered.startswith(("contact", "phone", "tel", "whatsapp"))
    ):
        existing = str(payload.get("phone_join_info") or "")
        cleaned = _clean_connection_line(line)
        payload["phone_join_info"] = " ".join(part for part in (existing, cleaned) if part).strip()
        return
    if _is_ignored_detail_line(line):
        return
    if str(payload.get("name") or "").lower() == line.lower():
        return
    if lowered.startswith("location:"):
        location = _clean_fragment(line.split(":", 1)[1])
        if not location:
            return
        if ADDRESS_RE.search(location) or _looks_like_address_fallback(location):
            payload.setdefault("address_line1", location)
        else:
            payload.setdefault("venue_name", location)
        return
    if lowered.startswith(("adres:", "adres :")):
        address = _clean_fragment(re.sub(r"^adres\s*:?\s*", "", line, flags=re.IGNORECASE))
        if address:
            payload.setdefault("address_line1", address)
        return
    if line.startswith(("http://", "https://")) and payload.get("online_url"):
        return
    if ADDRESS_RE.search(line):
        payload.setdefault("address_line1", line)
        return
    if _looks_like_address_fallback(line):
        payload.setdefault("address_line1", line)
        return
    if payload.get("address_line1") and not payload.get("city") and _looks_like_city_line(line):
        payload["city"] = line
        return
    if _looks_like_format_text(line):
        existing = str(payload.get("formats") or "")
        payload["formats"] = ", ".join(part for part in (existing, line) if part).strip(", ")
        return
    if not payload.get("name"):
        payload["name"] = line
        return
    if not payload.get("venue_name") and not _looks_like_format_text(line):
        payload["venue_name"] = line
        return


def _looks_like_next_meeting_name(line: str) -> bool:
    cleaned = _clean_meeting_name_line(line)
    if not cleaned:
        return False
    if _is_timezone_only_line(cleaned):
        return False
    lowered = cleaned.lower()
    if _is_ignored_detail_line(cleaned) or lowered.startswith(("adres", "zoom", "meeting id")):
        return False
    if any(term in lowered for term in ("zoom", "meeting id", "passcode", "hasło")):
        return False
    if lowered.startswith(("online ", "telephone ", "phone ")):
        return False
    if TIME_RE.search(cleaned) or DAY_RE.search(cleaned):
        return False
    if ADDRESS_RE.search(cleaned):
        return False
    return bool(any(char.isalpha() for char in cleaned))


def _clean_meeting_name_line(line: str) -> str:
    cleaned = _clean_fragment(line)
    cleaned = cleaned.replace("\u200b", "")
    cleaned = re.sub(r"^(grupa|group)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("“", "").replace("”", "").replace("„", "").replace('"', "")
    cleaned = re.sub(r"\((?:mityng|miting|meeting)[^)]+\)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(TEXT_STRIP_CHARS)
    return cleaned


def _clean_connection_line(line: str) -> str:
    cleaned = re.sub(r"\bAktywny\s+link\b", "", line, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bAktywny\b", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip(TEXT_STRIP_CHARS)


def _clean_schedule_remainder(text: str) -> str:
    cleaned = re.sub(
        r"^(?:każdy|każda|codziennie)?\s*[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ-]*\s*"
        r"(?:o\s+)?godzinie\s*:?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b(?:PL|UK)\s*:?\s*$", "", cleaned, flags=re.IGNORECASE)
    if _is_timezone_only_line(cleaned):
        return ""
    return _clean_fragment(cleaned)


def _clean_direct_listing_time_remainder(line: str, time: str) -> str:
    remainder = _clean_fragment(line.replace(time, "", 1))
    remainder = _clean_fragment(DAY_RE.sub("", remainder, count=1))
    remainder = re.sub(r"\s+", " ", remainder).strip(TEXT_STRIP_CHARS)
    remainder = re.sub(
        r"^(?:time\s*:|every\s+at|every|at)\s*",
        "",
        remainder,
        flags=re.IGNORECASE,
    )
    remainder = re.sub(
        r"^[–—-]?\s*(?:\d{1,2}(?::|\.|;)\d{2}|\d{3,4}|\d{1,2})"
        r"\s*(?:am|pm|a\.m\.|p\.m\.)?\s*(?:to|-|–|—)\s*"
        r"(?:\d{1,2}(?::|\.|;)\d{2}|\d{3,4}|\d{1,2})"
        r"\s*(?:am|pm|a\.m\.|p\.m\.)?\s*[–—-]?\s*",
        "",
        remainder,
        flags=re.IGNORECASE,
    )
    remainder = re.sub(
        r"^[–—-]?\s*(?:\d{1,2}(?::|\.|;)?\d{2}|\d{1,2})"
        r"\s*(?:am|pm|a\.m\.|p\.m\.)?\s*[–—-]?\s*",
        "",
        remainder,
        flags=re.IGNORECASE,
    )
    remainder = re.sub(
        r"^[|–—-]+\s*(?:\d{1,2}(?::|\.|;)?\d{2}|\d{1,2})"
        r"\s*(?:am|pm|a\.m\.|p\.m\.)?\s*",
        "",
        remainder,
        flags=re.IGNORECASE,
    )
    remainder = re.sub(
        r"\bto\s*(?:\d{1,2}(?::|\.|;)?\d{2}|\d{1,2})"
        r"\s*(?:am|pm|a\.m\.|p\.m\.)?\b",
        "",
        remainder,
        flags=re.IGNORECASE,
    )
    return _clean_fragment(remainder)


def _direct_listing_section_name(paragraph: Tag) -> str | None:
    strongs = [_clean_text(strong) for strong in paragraph.select("strong")]
    for strong in strongs:
        if strong and not (DAY_RE.search(strong) or TIME_RE.search(strong)):
            return _clean_meeting_name_line(strong)
    return None


def _direct_listing_name(paragraph: Tag, section_name: str | None) -> str | None:
    strongs = [_clean_text(strong) for strong in paragraph.select("strong")]
    for strong in strongs:
        if not strong or DAY_RE.search(strong) or TIME_RE.search(strong):
            continue
        if ":" in strong:
            continue
        return _clean_meeting_name_line(strong)
    return _clean_meeting_name_line(section_name or "") or None


def _merge_direct_listing_line(payload: dict[str, str], line: str) -> None:
    if _is_non_meeting_detail_line(line):
        return
    lowered = line.lower()
    if str(payload.get("name") or "").lower() == lowered:
        return
    if lowered.startswith("city "):
        payload.setdefault("city", _clean_fragment(line[5:]))
        return
    if _is_connection_line(line) or lowered.startswith(("contact", "phone", "tel", "whatsapp")):
        _merge_day_section_line(payload, line)
        return
    if _looks_like_address_fallback(line):
        payload.setdefault("address_line1", line)
        return
    _merge_day_section_line(payload, line)


def _structured_text_start_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        if line.startswith("All meetings open"):
            return index + 1
    try:
        return lines.index("Number found:") + 1
    except ValueError:
        return 0


def _is_structured_text_meeting_start(lines: list[str], index: int) -> bool:
    return bool(
        index + 2 < len(lines)
        and _structured_text_day(lines[index + 1])
        and _first_time_match(lines[index + 2])
    )


def _next_structured_text_meeting_index(lines: list[str], start_index: int) -> int:
    for index in range(start_index, len(lines) - 2):
        if _is_structured_text_meeting_start(lines, index):
            return index
    return len(lines)


def _structured_text_day(line: str) -> str:
    cleaned = re.sub(r"^\(\d+\)\s*", "", line).strip()
    day = _first_match(DAY_RE, cleaned)
    return day or ""


def _day_from_schedule_line(line: str) -> str | None:
    if day := _first_match(DAY_RE, line):
        return day.rstrip("s").title()
    match = re.search(
        r"\b(sundays|mondays|tuesdays|wednesdays|thursdays|fridays|saturdays)\b",
        line,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return match.group(1).removesuffix("s").title()


def _previous_sequence_name(lines: list[str], schedule_index: int) -> str | None:
    for index in range(schedule_index - 1, max(-1, schedule_index - 6), -1):
        candidate = _clean_meeting_name_line(lines[index])
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in {
            "meetings",
            "meeting",
            "new meeting",
            "more info",
            "our services",
            "trusted servant",
        }:
            continue
        if lowered.isdigit() or _looks_like_address_fallback(candidate):
            continue
        if TIME_RE.search(candidate) or _day_from_schedule_line(candidate):
            continue
        if _is_instruction_line(candidate) or _is_ignored_detail_line(candidate):
            continue
        if any(term in lowered for term in ("zoom link", "click here", "hybrid meetings")):
            continue
        return candidate
    return None


def _sequence_detail_lines(lines: list[str], start_index: int) -> list[str]:
    details: list[str] = []
    stop_terms = {
        "more info",
        "our services",
        "the 12 traditions",
        "all hybrid meetings are available through the following",
    }
    for index, line in enumerate(lines[start_index : start_index + 10], start=start_index):
        cleaned = _clean_fragment(line)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if _day_from_schedule_line(cleaned) and TIME_RE.search(cleaned):
            break
        if lowered in stop_terms:
            break
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if _looks_like_next_meeting_name(cleaned) and (
            _day_from_schedule_line(next_line) and TIME_RE.search(next_line)
        ):
            break
        if lowered.isdigit():
            break
        details.append(cleaned)
    return details


def _merge_sequence_detail_line(payload: dict[str, Any], line: str) -> None:
    lowered = line.lower()
    if lowered.startswith("begins "):
        return
    if lowered in {"(in person)", "in person", "online", "hybrid"}:
        payload.setdefault("attendance_option", line.strip("()"))
        return
    if re.fullmatch(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}", line):
        existing = str(payload.get("phone_join_info") or "")
        payload["phone_join_info"] = " ".join(part for part in (existing, line) if part).strip()
        return
    if (
        payload.get("address_line1")
        and not payload.get("city")
        and _looks_like_postal_city_line(line)
    ):
        payload["city"] = line
        return
    if not payload.get("address_line1") and not payload.get("city") and _looks_like_city_line(line):
        payload["city"] = line
        return
    _merge_day_section_line(payload, line)


def _is_placeholder_line(line: str) -> bool:
    return line.strip() in {"", "\u200b"}


def _is_connection_line(line: str) -> bool:
    lowered = line.lower()
    return any(
        term in lowered
        for term in (
            "access code",
            "click here",
            "meeting id",
            "passcode",
            "password",
            "zoom",
        )
    )


def _is_instruction_line(line: str) -> bool:
    lowered = line.lower()
    return any(
        term in lowered
        for term in (
            "attendance is limited",
            "enter by",
            "main entrance",
            "not wheelchair",
            "wheelchair",
        )
    )


def _looks_like_address_fallback(line: str) -> bool:
    lowered = line.lower()
    if "@" in line or _is_timezone_only_line(line):
        return False
    if any(term in lowered for term in ("meeting id", "passcode", "hasło", "contact")):
        return False
    return any(char.isdigit() for char in line) and len(line) <= 180


def _is_timezone_only_line(line: str) -> bool:
    cleaned = re.sub(TIME_RE, "", line)
    cleaned = re.sub(
        r"\b(?:PL|UK|GMT|UTC|CET|CEST|BST|EST|EDT|CST|CDT|MST|MDT|PST|PDT)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[\s:|,;/\\()–—-]+", "", cleaned)
    return not cleaned


def _is_ignored_detail_line(line: str) -> bool:
    lowered = line.lower().strip()
    return lowered in {"aktywny", "aktywny link", "link", "adres:", "adres :"}


def _is_non_meeting_detail_line(line: str) -> bool:
    lowered = line.lower().strip()
    if NON_MEETING_URL_RE.search(line):
        return True
    return any(
        phrase in lowered
        for phrase in (
            "a twelve step fellowship",
            "addicts seeking recovery",
            "copyright",
            "privacy policy",
        )
    )


def _looks_like_format_text(text: str) -> bool:
    compact = re.sub(r"[\s/|.()-]", "", text).lower()
    letters = [char for char in text if char.isalpha()]
    has_uppercase_abbreviation = (
        bool(letters) and " " not in text and all(char.isupper() for char in letters)
    )
    return bool(compact) and len(compact) <= 18 and ("/" in text or has_uppercase_abbreviation)


def _looks_like_city_line(text: str) -> bool:
    lowered = text.lower()
    if any(
        term in lowered
        for term in (
            "book",
            "club",
            "clubhouse",
            "meeting",
            "newcomer",
            "passcode",
            "smoking",
            "step",
            "study",
            "tradition",
            "zoom",
        )
    ):
        return False
    return not any(char.isdigit() for char in text) and len(text.split()) <= 4


def _looks_like_postal_city_line(text: str) -> bool:
    if "@" in text:
        return False
    return bool(
        re.fullmatch(
            r"[A-Za-z'.\s-]+,\s*[A-Z]{2}(?:\s+[A-Z0-9 -]{3,10})?",
            text.strip(),
        )
    )


def _clean_fragment(text: str) -> str:
    return text.strip(TEXT_STRIP_CHARS)


def _append_pending_day_section(
    meetings: list[ExtractedMeeting],
    payload: dict[str, Any],
    source_page_url: str,
    page_score: float,
    container_index: int,
    row_index: int,
) -> None:
    cleaned = _without_empty(payload)
    if not _looks_like_meeting_payload(cleaned):
        return
    confidence, signals = confidence_for_payload(
        cleaned,
        method="heuristic_day_section",
        page_score=page_score,
        repeated_structure=True,
    )
    meetings.append(
        ExtractedMeeting(
            payload={**cleaned, "row_index": row_index},
            method="heuristic_day_section",
            confidence=confidence,
            source_page_url=source_page_url,
            signals=signals,
            selector_hint=f"day_section:{container_index}",
        )
    )


def _meeting_url_or_none(url: str) -> str | None:
    if NON_MEETING_URL_RE.search(url):
        return None
    if ONLINE_MEETING_URL_RE.search(url):
        return url
    return None


def _first_url(text: str) -> str | None:
    match = re.search(r"https?://\S+", text)
    return match.group(0) if match else None


def _normalize_extracted_time(time: str) -> str:
    stripped = time.strip()
    lowered = stripped.lower()
    if lowered == "12 noon":
        return "12:00 pm"
    if lowered == "midnight":
        return "12:00 am"
    stripped = re.sub(r"^kl\.?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(
        r"\s*(?:to|-|–|—)\s*\d{1,2}(?:(?::|\.)\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?\s*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\b([ap])\.m\.?\b", r"\1m", stripped, flags=re.IGNORECASE)
    normalized = re.sub(
        r"(?<=\d)(?:\.|;)(?=\d{2}\s*(?:am|pm)?\b)",
        ":",
        normalized,
        flags=re.IGNORECASE,
    )
    compact = re.fullmatch(r"(\d{3,4})\s*(am|pm)", normalized, flags=re.IGNORECASE)
    if compact is not None:
        digits = compact.group(1)
        return f"{int(digits[:-2])}:{digits[-2:]}{compact.group(2).lower()}"
    if re.fullmatch(r"(?:[01]?\d|2[0-3])", normalized):
        return f"{int(normalized)}:00"
    return normalized


def _day_name_from_index(value: object) -> str | None:
    try:
        day = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return DAY_INDEX_NAMES.get(day)


def _day_name_from_tsml_sort(value: str) -> str | None:
    match = re.match(r"\s*([0-6])-", value)
    if match is None:
        return None
    return DAY_INDEX_NAMES.get(int(match.group(1)))


def _time_from_tsml_sort(value: str) -> str | None:
    match = re.match(r"\s*[0-6]-(\d{1,2}:\d{2})", value)
    return match.group(1) if match else None


def _source_record_id_from_meeting_url(url: str) -> str | None:
    path = urlparse(url).path.strip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[-2] == "meetings":
        return parts[-1]
    return None


def _tsml_attendance_option(row: Tag, location_cell: Tag) -> str | None:
    classes = {
        str(class_name)
        for tag in (row, location_cell)
        for class_name in (tag.get("class") or [])
    }
    if "attendance-hybrid" in classes:
        return "hybrid"
    if "attendance-online" in classes:
        return "online"
    if "attendance-in_person" in classes:
        return "in person"
    return None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(0) if match else None


def _first_time_match(text: str) -> str | None:
    range_match = TIME_RANGE_TRAILING_MARKER_RE.search(text)
    if range_match is not None:
        return f"{range_match.group('start')}{range_match.group('marker')}"
    return _first_match(TIME_RE, text)


def _first_text(tag: Tag, selector: str) -> str | None:
    node = tag.select_one(selector)
    return _clean_text(node) if node else None


def _clean_text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split())


def _without_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if str(value or "").strip()}


def _looks_like_meeting_payload(payload: dict[str, Any]) -> bool:
    return bool(
        payload.get("day")
        and payload.get("time")
        and (
            payload.get("address_line1")
            or payload.get("venue_name")
            or payload.get("city")
            or payload.get("online_url")
            or payload.get("phone_join_info")
        )
    )


def _dedupe_extracted(meetings: list[ExtractedMeeting]) -> list[ExtractedMeeting]:
    deduped: list[ExtractedMeeting] = []
    seen: set[tuple[str, str, str, str]] = set()
    for meeting in meetings:
        payload = meeting.payload
        key = (
            str(payload.get("name") or "").lower(),
            str(payload.get("day") or "").lower(),
            str(payload.get("time") or "").lower(),
            str(payload.get("address_line1") or payload.get("online_url") or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(meeting)
    return deduped

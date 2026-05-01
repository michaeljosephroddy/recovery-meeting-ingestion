import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag

from app.adapters.html_config import configured_selectors, extract_records_from_html
from app.scraping.meeting_page_detector import score_html
from app.scraping.models import ExtractedMeeting
from app.scraping.scoring import confidence_for_payload

DAY_RE = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)\b",
    re.IGNORECASE,
)
TIME_RE = re.compile(
    r"\b(?:\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)|12\s*noon|midnight)"
    r"(?=\W|$)",
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
    "day": {"day", "weekday"},
    "time": {"time", "start", "start time"},
    "venue_name": {"venue", "location", "place"},
    "address_line1": {"address", "street"},
    "city": {"city", "town"},
    "formats": {"type", "types", "format", "formats"},
    "notes": {"notes", "details"},
    "online_url": {"online", "url", "link", "zoom"},
}
TEXT_STRIP_CHARS = " -|–—\u00a0"


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

    soup = BeautifulSoup(html, "html.parser")
    extracted.extend(_extract_bmlt_tables(soup, source_page_url, page_score))
    extracted.extend(_extract_tables(soup, source_page_url, page_score))
    extracted.extend(_extract_cards(soup, source_page_url, page_score))
    extracted.extend(_extract_day_sections(soup, source_page_url, page_score))
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
                if time := _first_match(TIME_RE, start_time):
                    payload["time"] = _normalize_extracted_time(time)
            elif time := _first_match(TIME_RE, _clean_text(cells[0])):
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
    containers = soup.select(".entry-content, article, main")
    for container_index, container in enumerate(containers):
        lines = _day_section_lines(container)
        if not lines:
            continue
        current_day = _day_from_title(container) or _day_from_title(soup)
        pending: dict[str, Any] | None = None
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
                current_day = day_heading
                continue
            time = _first_match(TIME_RE, line)
            if time and current_day:
                if pending is not None:
                    _append_pending_day_section(
                        meetings, pending, source_page_url, page_score, container_index, row_index
                    )
                    row_index += 1
                pending = {"day": current_day, "time": _normalize_extracted_time(time)}
                _merge_time_line_remainder(pending, line, time)
                continue
            if pending is not None:
                _merge_day_section_line(pending, line)
        if pending is not None:
            _append_pending_day_section(
                meetings, pending, source_page_url, page_score, container_index, row_index
            )
    return meetings


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
        if time := _first_match(TIME_RE, time_value):
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
    time = _first_match(TIME_RE, text)
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


def _day_section_lines(container: Tag) -> list[str]:
    lines: list[str] = []
    for node in container.select("h1, h2, h3, h4, p, li"):
        text = node.get_text("\n", strip=True)
        for line in text.splitlines():
            cleaned = _clean_fragment(line)
            if cleaned:
                lines.append(cleaned)
    return lines


def _day_from_title(container: Tag | BeautifulSoup) -> str | None:
    title = container.select_one("h1, h2, h3, title")
    if title is None:
        return None
    return _day_heading_or_none(_clean_text(title))


def _day_heading_or_none(text: str) -> str | None:
    cleaned = _clean_fragment(text)
    if len(cleaned) > 20 or TIME_RE.search(cleaned):
        return None
    lowered = cleaned.lower()
    for day in ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"):
        if lowered == day or lowered == f"{day}s":
            return day.title()
    return None


def _merge_time_line_remainder(payload: dict[str, Any], line: str, time: str) -> None:
    remainder = _clean_fragment(line.replace(time, "", 1))
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
    lowered = line.lower()
    if "zoom" in lowered or "meeting id" in lowered or "passcode" in lowered:
        existing = str(payload.get("phone_join_info") or "")
        payload["phone_join_info"] = " ".join(part for part in (existing, line) if part).strip()
        return
    if ADDRESS_RE.search(line):
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


def _looks_like_format_text(text: str) -> bool:
    compact = re.sub(r"[\s/|.()-]", "", text).lower()
    letters = [char for char in text if char.isalpha()]
    has_uppercase_abbreviation = (
        bool(letters) and " " not in text and all(char.isupper() for char in letters)
    )
    return bool(compact) and len(compact) <= 18 and ("/" in text or has_uppercase_abbreviation)


def _looks_like_city_line(text: str) -> bool:
    lowered = text.lower()
    if any(term in lowered for term in ("meeting", "smoking", "zoom", "passcode")):
        return False
    return not any(char.isdigit() for char in text) and len(text.split()) <= 4


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


def _normalize_extracted_time(time: str) -> str:
    lowered = time.lower().strip()
    if lowered == "12 noon":
        return "12:00 pm"
    if lowered == "midnight":
        return "12:00 am"
    return time


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(0) if match else None


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

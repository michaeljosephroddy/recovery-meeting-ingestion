import asyncio
import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.adapters.base import RawMeeting
from app.sources.registry import Source

_SOURCE_IDS = {
    "na-40333db921fd",
    "na-d29507d2e6d6",
    "na-741664cfd8df",
    "na-318bd9c44950",
    "na-d4eceee5b4d4",
    "na-494e4e542045",
}
_DAY_NAMES = {
    "monday": "Monday",
    "mondays": "Monday",
    "tuesday": "Tuesday",
    "tuesdays": "Tuesday",
    "wednesday": "Wednesday",
    "wednesdays": "Wednesday",
    "thursday": "Thursday",
    "thursdays": "Thursday",
    "friday": "Friday",
    "fridays": "Friday",
    "saturday": "Saturday",
    "saturdays": "Saturday",
    "sunday": "Sunday",
    "sundays": "Sunday",
}
_RU_DAYS = {
    "понедельник": "Monday",
    "вторник": "Tuesday",
    "среда": "Wednesday",
    "четверг": "Thursday",
    "пятница": "Friday",
    "суббота": "Saturday",
    "воскресенье": "Sunday",
    "воскресение": "Sunday",
}
_ZERO_INDEXED_DAYS = {
    0: "Sunday",
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
}
_TIME_PREFIX_RE = re.compile(
    r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap]\.?\s*m\.?|[ap]m)\b\s*[-–]?\s*(.*)$",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap]\.?\s*m\.?|[ap]m)?\b", re.IGNORECASE)
_TIME_RANGE_RE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(?:-|–|—)\s*\d{1,2}(?::\d{2})?\s*([ap]\.?\s*m\.?|[ap]m)\b",
    re.IGNORECASE,
)
_DAY_TIME_RE = re.compile(
    r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?\s*[-–]\s*(.+)$",
    re.IGNORECASE,
)
_BELARUS_GROUP_INDEX_URL = "https://na-rb.by/groups/"
_CT_BMLTWF_URL = "https://ctna.org/wp-json/bmltwf/v1/bmltserver/meetings"


async def fetch_source_specific_na_records(
    source: Source,
    *,
    user_agent: str,
) -> list[RawMeeting] | None:
    if source.id not in _SOURCE_IDS:
        return None
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        if source.id == "na-40333db921fd":
            response = await client.get(_CT_BMLTWF_URL)
            response.raise_for_status()
            return raw_records_from_ct_bmltwf_payload(source, response.json())
        if source.id == "na-d4eceee5b4d4":
            index_response = await client.get(source.url)
            index_response.raise_for_status()
            links = _thailand_meeting_links(source.url, index_response.text)
            responses = await asyncio.gather(*(client.get(link) for link in links))
            records: list[RawMeeting] = []
            for response in responses:
                response.raise_for_status()
                records.extend(
                    raw_records_from_thailand_html(source, response.text, str(response.url))
                )
            return records
        if source.id == "na-494e4e542045":
            index_response = await client.get(_BELARUS_GROUP_INDEX_URL)
            index_response.raise_for_status()
            links = _belarus_group_links(index_response.text)
            responses = await asyncio.gather(*(client.get(link) for link in links))
            records = []
            for response in responses:
                response.raise_for_status()
                records.extend(
                    raw_records_from_belarus_html(source, response.text, str(response.url))
                )
            return records
        source_url = (
            "https://nabermuda.org/bermuda-meetings/"
            if source.id == "na-318bd9c44950"
            else source.url
        )
        response = await client.get(source_url)
        response.raise_for_status()
    if source.id == "na-d29507d2e6d6":
        return raw_records_from_nrvana_html(source, response.text, str(response.url))
    if source.id == "na-741664cfd8df":
        return raw_records_from_luzon_html(source, response.text, str(response.url))
    if source.id == "na-318bd9c44950":
        return raw_records_from_bermuda_html(source, response.text, str(response.url))
    return None


def raw_records_from_ct_bmltwf_payload(source: Source, payload: object) -> list[RawMeeting]:
    rows: object
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        rows = json.loads(payload["message"])
    else:
        rows = payload
    if not isinstance(rows, list):
        return []
    records: list[RawMeeting] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("published") is not True:
            continue
        day = _ZERO_INDEXED_DAYS.get(_int_or_none(row.get("day")) or -1)
        start = _text(row.get("startTime"))
        if day is None or not start:
            continue
        payload = {
            "source_record_id": f"ctna-{row.get('id')}",
            "name": _text(row.get("name")),
            "day": day,
            "time": start,
            "venue_name": _text(row.get("location_text")),
            "address_line1": _text(row.get("location_street")),
            "city": _text(row.get("location_municipality")),
            "region": "Connecticut",
            "postal_code": _text(row.get("location_postal_code_1")),
            "country": "United States",
            "latitude": _float_or_none(row.get("latitude")),
            "longitude": _float_or_none(row.get("longitude")),
            "online_url": _text(row.get("virtual_meeting_link")),
            "phone_join_info": _phone_join_info(row),
            "formats": [str(item) for item in row.get("formatIds") or []],
            "attendance_option": _attendance_option(row),
            "extraction": {"method": "ctna_bmltwf", "confidence": 0.95},
        }
        records.append(_raw_record(source, _CT_BMLTWF_URL, payload))
    return records


def raw_records_from_nrvana_html(
    source: Source,
    html: str,
    source_url: str | None = None,
) -> list[RawMeeting]:
    lines = _content_lines(html)
    lines = _slice_lines(lines, "Meetings", "Meeting Key:")
    records: list[RawMeeting] = []
    current_day: str | None = None
    for index, line in enumerate(lines):
        if day := _english_day(line):
            current_day = day
            continue
        if current_day is None or index == 0 or _parse_time(line) is None:
            continue
        name = lines[index - 1]
        if _english_day(name):
            continue
        details = _following_block(lines, index + 1)
        payload = _payload_from_nrvana_block(source, current_day, line, name, details, len(records))
        if payload:
            records.append(_raw_record(source, source_url or source.url, payload))
    return records


def raw_records_from_luzon_html(
    source: Source,
    html: str,
    source_url: str | None = None,
) -> list[RawMeeting]:
    lines = _slice_lines(_content_lines(html), "Mondays", "Note:")
    records: list[RawMeeting] = []
    current_day: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if day := _english_day(line):
            current_day = day
            index += 1
            continue
        split = _split_time_prefix(line)
        if current_day is None or split is None:
            index += 1
            continue
        time_text, remainder = split
        block, index = _consume_luzon_block(lines, index + 1)
        if remainder:
            block.insert(0, remainder)
        payload = _payload_from_luzon_block(source, current_day, time_text, block, len(records))
        if payload:
            records.append(_raw_record(source, source_url or source.url, payload))
    return records


def raw_records_from_bermuda_html(
    source: Source,
    html: str,
    source_url: str | None = None,
) -> list[RawMeeting]:
    lines = _slice_lines(_content_lines(html), "B.I.A.N.A Meetings Schedule", "Request")
    records: list[RawMeeting] = []
    current_day: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if day := _english_day(line):
            current_day = day
            index += 1
            continue
        next_line_starts_location = (
            index + 1 < len(lines) and lines[index + 1].casefold().startswith("location")
        )
        if current_day is None or not next_line_starts_location:
            index += 1
            continue
        block, index = _consume_bermuda_block(lines, index + 1)
        payload = _payload_from_bermuda_block(source, current_day, line, block, len(records))
        if payload:
            records.append(_raw_record(source, source_url or source.url, payload))
    return records


def raw_records_from_thailand_html(
    source: Source,
    html: str,
    source_url: str | None = None,
) -> list[RawMeeting]:
    source_url = source_url or source.url
    lines = _content_lines(html)
    records: list[RawMeeting] = []
    for index, line in enumerate(lines):
        match = _DAY_TIME_RE.search(line)
        if match is None:
            continue
        day = _english_day(match.group(1))
        time_text = _parse_time(match.group(2))
        if day is None or time_text is None:
            continue
        block = _following_thailand_block(lines, index + 1)
        if _is_closed_block(block):
            continue
        payload = _payload_from_thailand_block(
            source,
            day,
            time_text,
            block,
            source_url,
            len(records),
        )
        if payload:
            records.append(_raw_record(source, source_url, payload))
    return records


def raw_records_from_belarus_html(
    source: Source,
    html: str,
    source_url: str | None = None,
) -> list[RawMeeting]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[RawMeeting] = []
    for table_index, table in enumerate(soup.find_all("table")):
        rows = [
            [_clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            for row in table.find_all("tr")
        ]
        if not any(cells and cells[0].casefold() == "расписание" for cells in rows):
            continue
        name = _belarus_group_name(table) or source.name
        address = _belarus_group_address(table)
        city = _belarus_city(address)
        current_day: str | None = None
        for row_index, cells in enumerate(rows):
            text = " ".join(cells)
            if "рабочее" in text.casefold() or not cells:
                continue
            if day := _russian_day(cells[0]):
                current_day = day
                cells = cells[1:]
            time = _first_time(cells)
            if current_day is None or time is None:
                continue
            payload = {
                "source_record_id": f"belarus-{table_index}-{row_index}-{current_day}-{time}",
                "name": name,
                "day": current_day,
                "time": time,
                "address_line1": address,
                "city": city,
                "country": "Belarus",
                "timezone": "Europe/Minsk",
                "formats": [_clean_text(part) for part in cells if part and part != time],
                "attendance_option": "in_person",
                "extraction": {"method": "belarus_schedule_tables", "confidence": 0.82},
            }
            records.append(_raw_record(source, source_url or source.url, payload))
    return records


def _payload_from_nrvana_block(
    source: Source,
    day: str,
    time_line: str,
    name: str,
    details: list[str],
    index: int,
) -> dict[str, Any] | None:
    start = _parse_time(time_line)
    if start is None:
        return None
    format_lines = [line for line in details if line.startswith("(") and line.endswith(")")]
    location_lines = [line for line in details if line not in format_lines]
    address_index = next(
        (i for i, line in enumerate(location_lines) if _looks_like_address(line)),
        0,
    )
    venue_lines = location_lines[:address_index]
    address = location_lines[address_index] if address_index < len(location_lines) else None
    city_line = location_lines[address_index + 1] if address_index + 1 < len(location_lines) else ""
    payload: dict[str, Any] = {
        "source_record_id": f"nrvana-{index}-{day}-{start}",
        "name": name,
        "day": day,
        "time": start,
        "venue_name": " ".join(venue_lines) or None,
        "address_line1": address,
        "city": _city_from_us_line(city_line),
        "region": "Virginia",
        "country": "United States",
        "formats": format_lines,
        "attendance_option": "in_person",
        "extraction": {"method": "nrvana_stacked_schedule", "confidence": 0.88},
    }
    return payload


def _payload_from_luzon_block(
    source: Source,
    day: str,
    time_text: str,
    block: list[str],
    index: int,
) -> dict[str, Any] | None:
    start = _parse_time(time_text)
    if start is None:
        return None
    formats = [line.strip("()") for line in block if line.startswith("(") and line.endswith(")")]
    name_index = next((i for i, line in enumerate(block) if "group" in line.casefold()), None)
    if name_index is None:
        return None
    city_lines = [line for line in block[:name_index] if not line.startswith("(")]
    city = _clean_text(" ".join(city_lines).replace(" ,", ","))
    name = _clean_luzon_name(block[name_index])
    trailing = block[name_index + 1 :]
    address_lines: list[str] = []
    contact: str | None = None
    for line in trailing:
        if "contact" in line.casefold():
            before, _, after = line.partition("Contact")
            if before.strip():
                address_lines.append(before.strip())
            contact = f"Contact{after}".strip()
            break
        address_lines.append(line)
    return {
        "source_record_id": f"luzon-{index}-{day}-{start}",
        "name": name,
        "day": day,
        "time": start,
        "address_line1": ", ".join(address_lines) or None,
        "city": city or None,
        "country": "Philippines",
        "timezone": "Asia/Manila",
        "formats": formats,
        "phone_join_info": contact,
        "attendance_option": "in_person",
        "extraction": {"method": "luzon_weebly_schedule", "confidence": 0.82},
    }


def _payload_from_bermuda_block(
    source: Source,
    day: str,
    name_line: str,
    block: list[str],
    index: int,
) -> dict[str, Any] | None:
    time_line = next((line for line in block if _parse_time(line) is not None), "")
    start = _parse_time(time_line)
    if start is None:
        return None
    location_mode = next((line for line in block if line.casefold().startswith("location")), "")
    address_lines = [
        line
        for line in block
        if not line.casefold().startswith(("location", "zoom", "world committee"))
        and _parse_time(line) is None
    ]
    online_lines = [
        line for line in block if line.casefold().startswith(("zoom", "world committee"))
    ]
    attendance = "online" if "online" in location_mode.casefold() and not address_lines else (
        "hybrid" if "hybrid" in location_mode.casefold() or online_lines else "in_person"
    )
    return {
        "source_record_id": f"bermuda-{index}-{day}-{start}",
        "name": re.sub(r"\s*\((?:Open|Closed)\)\s*$", "", name_line, flags=re.IGNORECASE),
        "day": day,
        "time": start,
        "venue_name": address_lines[0] if len(address_lines) > 1 else None,
        "address_line1": ", ".join(address_lines) or None,
        "country": "Bermuda",
        "timezone": "Atlantic/Bermuda",
        "phone_join_info": "; ".join(online_lines) or None,
        "formats": re.findall(r"\((Open|Closed)\)", name_line, flags=re.IGNORECASE),
        "attendance_option": attendance,
        "extraction": {"method": "bermuda_wordpress_schedule", "confidence": 0.88},
    }


def _payload_from_thailand_block(
    source: Source,
    day: str,
    time_text: str,
    block: list[str],
    source_url: str,
    index: int,
) -> dict[str, Any] | None:
    name = _value_after_label(block, "Name:")
    address = _multiline_value_after_label(block, "Address:", {"Format:", "Contact:", "See Map"})
    formats = _multiline_value_after_label(block, "Format:", {"Contact:", "See Map"})
    if not name or not address:
        return None
    url_hash = hashlib.sha1(source_url.encode(), usedforsecurity=False).hexdigest()[:8]
    return {
        "source_record_id": f"thailand-{index}-{day}-{time_text}-{url_hash}",
        "name": name,
        "day": day,
        "time": time_text,
        "address_line1": address,
        "city": _thailand_city_from_url(source_url),
        "country": "Thailand",
        "timezone": "Asia/Bangkok",
        "formats": [formats] if formats else [],
        "attendance_option": "in_person",
        "extraction": {"method": "thailand_area_pages", "confidence": 0.84},
    }


def _raw_record(source: Source, source_url: str, payload: dict[str, Any]) -> RawMeeting:
    payload = {key: value for key, value in payload.items() if value not in (None, "", [])}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return RawMeeting(
        source_id=source.id,
        source_record_id=str(payload["source_record_id"]),
        source_url=source_url,
        payload=payload,
        content_hash=hashlib.sha256(encoded).hexdigest(),
    )


def _content_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    return [_clean_text(line) for line in text.splitlines() if _clean_text(line)]


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _text(value: object) -> str | None:
    text = _clean_text(value)
    return text or None


def _slice_lines(lines: list[str], start: str, end: str) -> list[str]:
    lower = [line.casefold() for line in lines]
    try:
        start_index = next(i for i, line in enumerate(lower) if start.casefold() in line)
    except StopIteration:
        start_index = 0
    try:
        end_index = next(
            i
            for i, line in enumerate(lower[start_index + 1 :], start_index + 1)
            if end.casefold() in line
        )
    except StopIteration:
        end_index = len(lines)
    return lines[start_index:end_index]


def _english_day(line: str) -> str | None:
    return _DAY_NAMES.get(line.casefold().strip(":"))


def _russian_day(line: str) -> str | None:
    return _RU_DAYS.get(line.casefold().strip(":"))


def _parse_time(line: str) -> str | None:
    line = _clean_text(line)
    range_match = _TIME_RANGE_RE.search(line)
    if range_match is not None:
        return _format_time(range_match.group(1), range_match.group(2), range_match.group(3))
    match = _TIME_RE.search(line)
    if match is None:
        return None
    return _format_time(match.group(1), match.group(2), match.group(3))


def _format_time(hour_text: str, minute_text: str | None, meridiem: str | None) -> str | None:
    hour = int(hour_text)
    minute = int(minute_text or "00")
    if minute > 59 or hour > 23:
        return None
    marker = re.sub(r"[^ap]", "", (meridiem or "").casefold())
    if marker.startswith("p") and hour < 12:
        hour += 12
    if marker.startswith("a") and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _split_time_prefix(line: str) -> tuple[str, str] | None:
    match = _TIME_PREFIX_RE.match(line)
    if match is None:
        return None
    time_text = _format_time(match.group(1), match.group(2), match.group(3))
    if time_text is None:
        return None
    return time_text, _clean_text(match.group(4))


def _following_block(lines: list[str], start_index: int) -> list[str]:
    block: list[str] = []
    for index in range(start_index, len(lines)):
        line = lines[index]
        if _english_day(line):
            break
        if index + 1 < len(lines) and _parse_time(lines[index + 1]) is not None:
            break
        block.append(line)
    return block


def _consume_luzon_block(lines: list[str], start_index: int) -> tuple[list[str], int]:
    block: list[str] = []
    index = start_index
    while index < len(lines):
        if _english_day(lines[index]) or _split_time_prefix(lines[index]) is not None:
            break
        block.append(lines[index])
        index += 1
    return block, index


def _consume_until_day(lines: list[str], start_index: int) -> tuple[list[str], int]:
    block: list[str] = []
    index = start_index
    while index < len(lines):
        if _english_day(lines[index]):
            break
        block.append(lines[index])
        index += 1
    return block, index


def _consume_bermuda_block(lines: list[str], start_index: int) -> tuple[list[str], int]:
    block: list[str] = []
    index = start_index
    while index < len(lines):
        if _english_day(lines[index]):
            break
        if (
            index > start_index
            and index + 1 < len(lines)
            and lines[index + 1].casefold().startswith("location")
        ):
            break
        block.append(lines[index])
        index += 1
    return block, index


def _following_thailand_block(lines: list[str], start_index: int) -> list[str]:
    block: list[str] = []
    for line in lines[start_index:]:
        if _DAY_TIME_RE.search(line) or "Need to add a new meeting" in line:
            break
        block.append(line)
    return block


def _looks_like_address(line: str) -> bool:
    street_pattern = r"\b(st|street|ave|avenue|road|rd|dr|drive|way|blvd|lane|ln)\b\.?"
    return bool(
        re.search(r"\d", line) and re.search(street_pattern, line, re.IGNORECASE)
    )


def _city_from_us_line(line: str) -> str | None:
    match = re.search(r"([A-Za-z .']+),?\s+V(?:a|A)\b", line)
    return _clean_text(match.group(1)) if match else None


def _clean_luzon_name(line: str) -> str:
    line = line.replace("“", "").replace("”", "").replace('"', "")
    line = re.sub(r"\bGroup(?:”\s*Group)?\b", "Group", line, flags=re.IGNORECASE)
    return _clean_text(line)


def _value_after_label(lines: list[str], label: str) -> str | None:
    for index, line in enumerate(lines):
        if line.casefold() == label.casefold() and index + 1 < len(lines):
            return lines[index + 1]
    return None


def _multiline_value_after_label(lines: list[str], label: str, terminators: set[str]) -> str | None:
    for index, line in enumerate(lines):
        if line.casefold() != label.casefold():
            continue
        values: list[str] = []
        for value in lines[index + 1 :]:
            if value in terminators or value.casefold().startswith("contact information"):
                break
            values.append(value)
        return " ".join(values) or None
    return None


def _is_closed_block(block: list[str]) -> bool:
    text = " ".join(block).casefold()
    return "closed until further notice" in text or "meeting is closed" in text


def _thailand_meeting_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for anchor in soup.find_all("a", href=True):
        url = urljoin(base_url, str(anchor["href"]))
        path = urlparse(url).path.rstrip("/")
        if path.startswith("/meetings/") and path != "/meetings":
            links.append(url)
    return sorted(set(links))


def _thailand_city_from_url(source_url: str) -> str | None:
    slug = urlparse(source_url).path.strip("/").split("/")[-1]
    slug = re.sub(r"-meetings?$", "", slug)
    return " ".join(part.capitalize() for part in slug.split("-")) or None


def _belarus_group_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for anchor in soup.find_all("a", href=True):
        url = urljoin(_BELARUS_GROUP_INDEX_URL, str(anchor["href"]))
        path = urlparse(url).path.strip("/")
        if path.startswith("groups/") and len(path.split("/")) >= 3:
            links.append(f"https://na-rb.by/{path}/")
    return sorted(set(links))


def _belarus_group_name(table: Tag) -> str | None:
    for previous in table.find_all_previous(["h1", "h2", "h3", "h4", "p"], limit=12):
        text = _clean_text(previous.get_text(" ", strip=True))
        if "группа" in text.casefold():
            return re.sub(r"^Группа\s+[«\"]?|[»\"]$", "", text, flags=re.IGNORECASE)
    return None


def _belarus_group_address(table: Tag) -> str | None:
    for previous in table.find_all_previous(["h1", "h2", "h3", "h4", "p", "table"], limit=8):
        text = _clean_text(previous.get_text(" ", strip=True))
        is_address = "ул" in text.casefold() or "пр" in text.casefold() or "г." in text.casefold()
        if is_address and "расписание" not in text.casefold():
            return text
    return None


def _belarus_city(address: str | None) -> str | None:
    if address is None:
        return None
    match = re.search(r"г\.\s*([^,]+)", address, flags=re.IGNORECASE)
    return _clean_text(match.group(1)) if match else None


def _first_time(cells: list[str]) -> str | None:
    for cell in cells:
        match = re.search(r"\b(\d{1,2}):(\d{2})", cell)
        if match:
            return f"{int(match.group(1)):02d}:{match.group(2)}"
    return None


def _phone_join_info(row: dict[str, Any]) -> str | None:
    parts = [
        _text(row.get("phone_meeting_number")),
        _text(row.get("virtual_meeting_additional_info")),
    ]
    return "; ".join(part for part in parts if part) or None


def _attendance_option(row: dict[str, Any]) -> str:
    has_address = bool(_text(row.get("location_street")) or _text(row.get("location_text")))
    has_online = bool(
        _text(row.get("virtual_meeting_link")) or _text(row.get("phone_meeting_number"))
    )
    if has_address and has_online:
        return "hybrid"
    if has_online:
        return "online"
    return "in_person"


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)  # type: ignore[arg-type]


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None

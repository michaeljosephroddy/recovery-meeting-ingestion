import hashlib
import json
import re
from collections.abc import Callable
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.adapters.base import RawMeeting
from app.sources.registry import Source

_SOURCE_URLS: dict[str, str] = {
    "ca-4b3b7087b949": "https://ca-maritimes.org/",
    "ca-f60993c27baf": "https://www.caquebec.org/reunions/",
    "ca-63a0c6bbe7d2": "https://ca-danmark.dk/moeder/",
    "ca-2915b40b65f2": "http://www.cagreece.org/meetings",
    "ca-e2f77889edc7": "http://ca-russia.com/gruppa/#zoom",
    "ca-60973398a3f3": "https://caoklahoma.org/",
    "ca-e4d3d7f0476f": "https://www.cawisconsin.org/Meetings.htm",
    "ca-200708853eaf": "https://canashville.com/",
    "ca-d7d0c4eae08f": "https://cacolumbusoh.org",
    "ca-f6c1ff14a8cb": "https://www.ca-texas.org/",
}
_PARSERS: dict[str, Callable[[Source, str, str], list[RawMeeting]]] = {}

_DAY_NAMES = {
    "sunday": "Sunday",
    "sundays": "Sunday",
    "monday": "Monday",
    "mondays": "Monday",
    "tuesday": "Tuesday",
    "tuesdays": "Tuesday",
    "wednesday": "Wednesday",
    "wednesdays": "Wednesday",
    "thursday": "Thursday",
    "thursdays": "Thursday",
    "friday": "Friday",
    "saturday": "Saturday",
}
_DAY_HEADINGS = {value.upper(): value for value in _DAY_NAMES.values()}
_FR_DAYS = ["Dimanche", "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
_GREEK_DAYS = {
    "ΔΕΥΤΕΡΑ": "Δευτέρα",
    "ΤΕΤΑΡΤΗ": "Τετάρτη",
    "ΠΑΡΑΣΚΕΥΗ": "Παρασκευή",
    "ΣΑΒΒΑΤΟ": "Σάββατο",
    "ΚΥΡΙΑΚΗ": "Κυριακή",
}
_TIME_RE = re.compile(r"\b(\d{1,2})(?::|\.)(\d{2})\s*([ap]\.?m\.?)?\b", re.IGNORECASE)
_TIME_WORD_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)\b", re.IGNORECASE)
_WISCONSIN_MEETING_RE = re.compile(
    r"^(?P<name>.+?)\s*[-–]\s*(?P<time>\d{1,2}:\d{2}\s*[AP]M)$",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(
    r"\b(PO Box|P\.O\.)|"
    r"\b(street|st\.?|avenue|ave\.?|road|rd\.?|drive|dr\.?|lane|ln\.?|"
    r"boulevard|blvd\.?|pike|way|rue|chemin|vej|gade)\b",
    re.IGNORECASE,
)


async def fetch_source_specific_ca_records(
    source: Source,
    *,
    user_agent: str,
) -> list[RawMeeting] | None:
    if source.id not in _SOURCE_URLS:
        return None
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        response = await client.get(_SOURCE_URLS[source.id])
        response.raise_for_status()
    parser = _PARSERS[source.id]
    return parser(source, response.text, str(response.url))


def _parser(source_id: str) -> Callable[
    [Callable[[Source, str, str], list[RawMeeting]]],
    Callable[[Source, str, str], list[RawMeeting]],
]:
    def decorate(
        parser: Callable[[Source, str, str], list[RawMeeting]],
    ) -> Callable[[Source, str, str], list[RawMeeting]]:
        _PARSERS[source_id] = parser
        return parser

    return decorate


@_parser("ca-63a0c6bbe7d2")
def raw_records_from_denmark_html(source: Source, html: str, source_url: str) -> list[RawMeeting]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for row_index, row in enumerate(_table_rows(soup), start=1):
        if len(row) < 4 or row[0].casefold() == "dag":
            continue
        day, name_text, time_text, address = row[:4]
        start = _first_time(time_text)
        if not start:
            continue
        name = _quoted_name(name_text) or _clean_text(re.split(r"\bDørene\b", name_text)[0])
        payload = {
            "source_record_id": f"denmark-{row_index}",
            "name": name,
            "day": day,
            "time": start,
            "address_line1": address,
            "country": "Denmark",
            "timezone": "Europe/Copenhagen",
            "formats": _format_notes(name_text),
            "extraction": {"method": "ca_denmark_table", "confidence": 0.94},
        }
        if "zoom" in address.casefold() or "zoom" in " ".join(row[4:]).casefold():
            payload["attendance_option"] = "online"
            payload["phone_join_info"] = _clean_text(" ".join([address, *row[4:]]))
            payload.pop("address_line1", None)
        records.append(_raw_record(source, source_url, payload))
    return records


@_parser("ca-f60993c27baf")
def raw_records_from_quebec_html(source: Source, html: str, source_url: str) -> list[RawMeeting]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[RawMeeting] = []
    for table_index, table in enumerate(soup.find_all("table")):
        day = _FR_DAYS[table_index % 7]
        rows = _table_rows(table)
        index = 0
        while index < len(rows):
            row = rows[index]
            if len(row) < 2 or not (start := _quebec_time(row[0])):
                index += 1
                continue
            block: list[list[str]] = []
            index += 1
            while index < len(rows) and not (rows[index] and _quebec_time(rows[index][0])):
                block.append(rows[index])
                index += 1
            payload = _quebec_payload(
                source_record_id=f"quebec-{table_index}-{len(records)}",
                day=day,
                time_text=start,
                name=row[1],
                block=block,
                online=table_index >= 7,
            )
            if payload:
                records.append(_raw_record(source, source_url, payload))
    return records


@_parser("ca-4b3b7087b949")
def raw_records_from_maritimes_html(source: Source, html: str, source_url: str) -> list[RawMeeting]:
    soup = BeautifulSoup(html, "html.parser")
    lines = _content_lines(soup)
    join_links = [
        urljoin(source_url, str(anchor["href"]))
        for anchor in soup.find_all("a", href=True)
        if _clean_text(anchor.get_text(" ", strip=True)).casefold() == "join now"
    ]
    records = []
    join_index = 0
    for index, line in enumerate(lines[:-1]):
        day_time = _day_at_time(lines[index + 1])
        if day_time is None:
            continue
        day, time_text = day_time
        payload = {
            "source_record_id": f"maritimes-{len(records)}",
            "name": line,
            "day": day,
            "time": time_text,
            "attendance_option": "online",
            "country": "Canada",
            "region": "Nova Scotia",
            "timezone": "America/Halifax",
            "extraction": {"method": "ca_maritimes_online_cards", "confidence": 0.93},
        }
        if join_index < len(join_links):
            payload["online_url"] = join_links[join_index]
            join_index += 1
        records.append(_raw_record(source, source_url, payload))
    return records


@_parser("ca-200708853eaf")
def raw_records_from_nashville_html(source: Source, html: str, source_url: str) -> list[RawMeeting]:
    return _records_from_name_before_time_blocks(
        source,
        source_url,
        _content_lines(BeautifulSoup(html, "html.parser")),
        method="ca_nashville_day_blocks",
        country="United States",
        region="Tennessee",
        city="Nashville",
        timezone="America/Chicago",
    )


@_parser("ca-d7d0c4eae08f")
def raw_records_from_columbus_html(source: Source, html: str, source_url: str) -> list[RawMeeting]:
    return _records_from_day_blocks(
        source,
        source_url,
        _content_lines(BeautifulSoup(html, "html.parser")),
        method="ca_columbus_day_blocks",
        country="United States",
        region="Ohio",
        city="Columbus",
        timezone="America/New_York",
    )


@_parser("ca-f6c1ff14a8cb")
def raw_records_from_texas_html(source: Source, html: str, source_url: str) -> list[RawMeeting]:
    lines = _slice_between(
        _content_lines(BeautifulSoup(html, "html.parser")),
        "MEETINGS IN THE GREATER HOUSTON AREA",
        "Other CA Meetings",
    )
    return _records_from_time_blocks(
        source,
        source_url,
        lines,
        method="ca_texas_time_blocks",
        country="United States",
        region="Texas",
        city="Houston",
        timezone="America/Chicago",
    )


@_parser("ca-e4d3d7f0476f")
def raw_records_from_wisconsin_html(source: Source, html: str, source_url: str) -> list[RawMeeting]:
    lines = _slice_between(
        _content_lines(BeautifulSoup(html, "html.parser")),
        "Southeastern WI",
        "This website is neither endorsed",
    )
    records = []
    current_day: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.upper() in _DAY_HEADINGS:
            current_day = _DAY_HEADINGS[line.upper()]
            index += 1
            continue
        match = _WISCONSIN_MEETING_RE.match(line)
        if current_day is None or match is None:
            index += 1
            continue
        block, index = _consume_until_next(lines, index + 1, _is_wisconsin_boundary)
        payload = _payload_from_name_time_block(
            source_record_id=f"wisconsin-{len(records)}",
            day=current_day,
            time_text=_first_time(match.group("time")) or match.group("time"),
            name=match.group("name"),
            block=block,
            country="United States",
            region="Wisconsin",
            timezone="America/Chicago",
            method="ca_wisconsin_line_schedule",
        )
        records.append(_raw_record(source, source_url, payload))
    return records


@_parser("ca-60973398a3f3")
def raw_records_from_oklahoma_html(source: Source, html: str, source_url: str) -> list[RawMeeting]:
    base_payload = {
        "name": "The Rock Stops Here Group",
        "venue_name": "Peppertree Square",
        "address_line1": "6444 NW Expressway Suite 241E",
        "city": "Oklahoma City",
        "region": "Oklahoma",
        "country": "United States",
        "timezone": "America/Chicago",
        "formats": "Discussion",
        "extraction": {"method": "ca_oklahoma_static_schedule", "confidence": 0.92},
    }
    records = []
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]:
        records.append(
            _raw_record(
                source,
                source_url,
                {
                    **base_payload,
                    "source_record_id": f"oklahoma-rock-{day.casefold()}",
                    "day": day,
                    "time": "8:00 pm",
                },
            )
        )
    records.append(
        _raw_record(
            source,
            source_url,
            {
                **base_payload,
                "source_record_id": "oklahoma-rock-sunday",
                "day": "Sunday",
                "time": "5:30 pm",
            },
        )
    )
    return records


@_parser("ca-2915b40b65f2")
def raw_records_from_greece_html(source: Source, html: str, source_url: str) -> list[RawMeeting]:
    text = "\n".join(_content_lines(BeautifulSoup(html, "html.parser")))
    zoom_links = re.findall(r"https://us\d+web\.zoom\.us/j/[^\s]+", text)
    primary_zoom = zoom_links[0] if zoom_links else None
    records = []
    for greek_day, day in _GREEK_DAYS.items():
        for match in re.finditer(rf"{greek_day}\s+(\d{{1,2}}:\d{{2}})", text):
            payload = {
                "source_record_id": f"greece-{greek_day.casefold()}-{match.group(1)}",
                "name": "CA Hellas Cyprus Online",
                "day": day,
                "time": match.group(1),
                "attendance_option": "online",
                "country": "Greece",
                "timezone": "Europe/Athens",
                "phone_join_info": "CA Hellas / Cyprus Zoom meeting",
                "extraction": {"method": "ca_greece_online_schedule", "confidence": 0.9},
            }
            if primary_zoom:
                payload["online_url"] = primary_zoom
            records.append(_raw_record(source, source_url, payload))
    return _dedupe_records(records)


@_parser("ca-e2f77889edc7")
def raw_records_from_russia_html(source: Source, html: str, source_url: str) -> list[RawMeeting]:
    lines = _content_lines(BeautifulSoup(html, "html.parser"))
    records = []
    for index, line in enumerate(lines):
        if "КАЖДЫЙ ДЕНЬ" not in line.upper():
            continue
        start = _first_time(line)
        if start is None:
            continue
        address = _nearest_previous(lines, index, "Санкт-Петербург")
        records.append(
            _raw_record(
                source,
                source_url,
                {
                    "source_record_id": "russia-daily",
                    "name": "Группа Каждый День",
                    "day": "daily",
                    "time": start,
                    "address_line1": address,
                    "city": "Санкт-Петербург",
                    "country": "Russia",
                    "timezone": "Europe/Moscow",
                    "extraction": {"method": "ca_russia_daily_group", "confidence": 0.9},
                },
            )
        )
    return records


def _records_from_day_blocks(
    source: Source,
    source_url: str,
    lines: list[str],
    *,
    method: str,
    country: str,
    region: str,
    city: str,
    timezone: str,
) -> list[RawMeeting]:
    records = []
    current_day: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.upper() in _DAY_HEADINGS:
            current_day = _DAY_HEADINGS[line.upper()]
            index += 1
            continue
        if current_day is None or not _is_time_line(line):
            index += 1
            continue
        time_text = _first_time(line)
        block, index = _consume_until_next(lines, index + 1, _is_day_or_time)
        if time_text is None or not block:
            continue
        name, details = _split_name_from_details(block)
        payload = _payload_from_name_time_block(
            source_record_id=f"{method}-{len(records)}",
            day=current_day,
            time_text=time_text,
            name=name,
            block=details,
            country=country,
            region=region,
            city=city,
            timezone=timezone,
            method=method,
        )
        if "no meeting" in " ".join(block).casefold():
            continue
        records.append(_raw_record(source, source_url, payload))
    return records


def _records_from_time_blocks(
    source: Source,
    source_url: str,
    lines: list[str],
    *,
    method: str,
    country: str,
    region: str,
    city: str,
    timezone: str,
) -> list[RawMeeting]:
    records = []
    current_day: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.upper() in _DAY_HEADINGS:
            current_day = _DAY_HEADINGS[line.upper()]
            index += 1
            continue
        if current_day is None or (time_text := _first_time(line)) is None:
            index += 1
            continue
        block, index = _consume_until_next(lines, index + 1, _is_day_or_time)
        if not block or "temporarily suspended" in " ".join(block).casefold():
            continue
        name, details = _split_name_from_details(block)
        payload = _payload_from_name_time_block(
            source_record_id=f"{method}-{len(records)}",
            day=current_day,
            time_text=time_text,
            name=name,
            block=details,
            country=country,
            region=region,
            city=city,
            timezone=timezone,
            method=method,
        )
        records.append(_raw_record(source, source_url, payload))
    return records


def _records_from_name_before_time_blocks(
    source: Source,
    source_url: str,
    lines: list[str],
    *,
    method: str,
    country: str,
    region: str,
    city: str,
    timezone: str,
) -> list[RawMeeting]:
    records = []
    current_day: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.upper() in _DAY_HEADINGS:
            current_day = _DAY_HEADINGS[line.upper()]
            index += 1
            continue
        if current_day is None or index + 1 >= len(lines):
            index += 1
            continue
        if lines[index + 1].casefold().startswith("time:"):
            name = line
            time_index = index + 1
        elif index + 2 < len(lines) and lines[index + 2].casefold().startswith("time:"):
            name = f"{line} {lines[index + 1]}"
            time_index = index + 2
        else:
            index += 1
            continue
        time_text = _first_time(lines[time_index])
        block = []
        index = time_index + 1
        while index < len(lines):
            if lines[index].upper() in _DAY_HEADINGS:
                break
            if index + 1 < len(lines) and lines[index + 1].casefold().startswith("time:"):
                break
            block.append(lines[index])
            index += 1
        if time_text is None:
            continue
        payload = _payload_from_name_time_block(
            source_record_id=f"{method}-{len(records)}",
            day=current_day,
            time_text=time_text,
            name=name,
            block=block,
            country=country,
            region=region,
            city=city,
            timezone=timezone,
            method=method,
        )
        records.append(_raw_record(source, source_url, payload))
    return records


def _payload_from_name_time_block(
    *,
    source_record_id: str,
    day: str,
    time_text: str,
    name: str,
    block: list[str],
    country: str,
    region: str,
    timezone: str,
    method: str,
    city: str | None = None,
) -> dict[str, object]:
    address_lines = _address_lines(block)
    venue = _venue_name(block)
    online_url = _first_url(block)
    has_zoom = online_url or any("zoom" in line.casefold() for line in block)
    payload: dict[str, object] = {
        "source_record_id": source_record_id,
        "name": _clean_name(name),
        "day": day,
        "time": time_text,
        "country": country,
        "region": region,
        "timezone": timezone,
        "formats": _format_notes(" ".join(line for line in block if not _looks_like_address(line))),
        "extraction": {"method": method, "confidence": 0.9},
    }
    if city and (address_lines or not has_zoom):
        payload["city"] = city
    if venue:
        payload["venue_name"] = venue
    if address_lines:
        payload["address_line1"] = " ".join(address_lines)
        payload["attendance_option"] = "hybrid" if has_zoom else "in_person"
    if has_zoom:
        payload["attendance_option"] = "hybrid" if address_lines else "online"
        payload["phone_join_info"] = " ".join(block)
        if online_url:
            payload["online_url"] = online_url
    return payload


def _quebec_payload(
    *,
    source_record_id: str,
    day: str,
    time_text: str,
    name: str,
    block: list[list[str]],
    online: bool,
) -> dict[str, object] | None:
    flattened = [_clean_text(cell) for row in block for cell in row if _clean_text(cell)]
    if not flattened:
        return None
    formats = flattened[0] if len(flattened[0]) <= 20 else None
    details = flattened[1:] if formats else flattened
    online_url = next((item for item in details if item.startswith("http")), None)
    zoom = " ".join(item for item in details if "zoom" in item.casefold() or item.startswith("http"))
    address = next((item for item in details if _looks_like_address(item)), None)
    city = next((item for item in details if re.search(r"\b[A-Z]\d[A-Z]\s*\d[A-Z]\d\b", item)), None)
    payload: dict[str, object] = {
        "source_record_id": source_record_id,
        "name": name,
        "day": day,
        "time": time_text,
        "country": "Canada",
        "region": "Quebec",
        "timezone": "America/Toronto",
        "formats": formats or "",
        "extraction": {"method": "ca_quebec_tables", "confidence": 0.93},
    }
    if online:
        payload["attendance_option"] = "online"
        payload["phone_join_info"] = zoom or " ".join(details)
        if online_url:
            payload["online_url"] = online_url
    else:
        payload["address_line1"] = address or " ".join(details[:2])
        if city:
            payload["city"] = city
    return payload


def _table_rows(soup: BeautifulSoup) -> list[list[str]]:
    rows = []
    for row in soup.find_all("tr"):
        cells = [_clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    return rows


def _content_lines(soup: BeautifulSoup) -> list[str]:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return [_clean_text(line) for line in soup.get_text("\n").splitlines() if _clean_text(line)]


def _slice_between(lines: list[str], start_marker: str, end_marker: str) -> list[str]:
    start = 0
    for index, line in enumerate(lines):
        if start_marker.casefold() in line.casefold():
            start = index + 1
            break
    end = len(lines)
    for index in range(start, len(lines)):
        if end_marker.casefold() in lines[index].casefold():
            end = index
            break
    return lines[start:end]


def _consume_until_next(
    lines: list[str],
    start: int,
    boundary: Callable[[str], bool],
) -> tuple[list[str], int]:
    block = []
    index = start
    while index < len(lines) and not boundary(lines[index]):
        block.append(lines[index])
        index += 1
    return block, index


def _is_wisconsin_boundary(line: str) -> bool:
    return line.upper() in _DAY_HEADINGS or _WISCONSIN_MEETING_RE.match(line) is not None


def _is_day_or_time(line: str) -> bool:
    return line.upper() in _DAY_HEADINGS or _is_time_line(line)


def _is_time_line(line: str) -> bool:
    cleaned = _clean_text(line)
    if cleaned.casefold().startswith("time:"):
        return True
    return _first_time(cleaned) is not None and len(cleaned) <= 18


def _first_time(value: str) -> str | None:
    cleaned = _clean_text(value).replace("TIME:", "").strip()
    match = _TIME_RE.search(cleaned) or _TIME_WORD_RE.search(cleaned)
    if match is None:
        if cleaned.casefold() == "midi":
            return "12:00"
        return None
    hour = int(match.group(1))
    minute = match.group(2) or "00"
    marker = (match.group(3) or "").casefold().replace(".", "")
    if marker == "pm" and hour < 12:
        hour += 12
    if marker == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute}"


def _quebec_time(value: str) -> str | None:
    if value.casefold() == "midi":
        return "12:00"
    return _first_time(value)


def _day_at_time(value: str) -> tuple[str, str] | None:
    match = re.match(r"([A-Za-z]+)s?\s+at\s+(.+)$", value.strip(), re.IGNORECASE)
    if match is None:
        return None
    day = _DAY_NAMES.get(match.group(1).casefold())
    time_text = _first_time(match.group(2))
    if day is None or time_text is None:
        return None
    return day, time_text


def _address_lines(block: list[str]) -> list[str]:
    lines = []
    for line in block:
        lowered = line.casefold()
        if (
            line.startswith("http")
            or "google map" in lowered
            or "meeting id" in lowered
            or "password" in lowered
            or lowered.startswith("zoom")
        ):
            continue
        if _looks_like_address(line) or (lines and re.search(r"\b[A-Z]{2}\s+\d{5}\b", line)):
            lines.append(line)
    return lines[:3]


def _venue_name(block: list[str]) -> str | None:
    for line in block:
        cleaned = _clean_text(line)
        lowered = cleaned.casefold()
        if (
            not cleaned
            or cleaned.startswith("http")
            or "meeting id" in lowered
            or "password" in lowered
            or lowered.startswith("zoom")
            or "google map" in lowered
            or _looks_like_address(cleaned)
        ):
            continue
        if re.search(r"\b[A-Z]{2}\s+\d{5}\b", cleaned):
            continue
        return cleaned
    return None


def _split_name_from_details(block: list[str]) -> tuple[str, list[str]]:
    skipped = {
        "(in person)",
        "in person",
        "(online)",
        "online",
        "zoom only",
        "zoom only meeting",
    }
    for index, line in enumerate(block):
        cleaned = _clean_name(line)
        if not cleaned or cleaned.casefold() in skipped:
            continue
        if _looks_like_address(cleaned) or cleaned.casefold().startswith(("open/", "closed/")):
            continue
        return cleaned, [*block[:index], *block[index + 1 :]]
    return "Recovery Meeting", block


def _looks_like_address(line: str) -> bool:
    return bool(_ADDRESS_RE.search(line))


def _first_url(block: list[str]) -> str | None:
    for line in block:
        match = re.search(r"https?://\S+", line)
        if match:
            return match.group(0)
    return None


def _nearest_previous(lines: list[str], index: int, marker: str) -> str | None:
    for previous in reversed(lines[max(0, index - 6) : index]):
        if marker.casefold() in previous.casefold():
            return previous
    return None


def _quoted_name(value: str) -> str | None:
    match = re.search(r"[“\"]([^”\"]+)[”\"]", value)
    return _clean_text(match.group(1)) if match else None


def _clean_name(value: str) -> str:
    value = re.sub(r"^\(?In Person\)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^\(?Online\)?\s*", "", value, flags=re.IGNORECASE)
    return _clean_text(value.strip("“”\""))


def _format_notes(value: str) -> str:
    notes = []
    for marker in ["Open", "Discussion", "Big Book", "Speaker", "Meditation", "12 & 12", "Closed"]:
        if marker.casefold() in value.casefold():
            notes.append(marker)
    return ", ".join(dict.fromkeys(notes))


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").replace("\ufeff", " ").split()).strip()


def _raw_record(source: Source, source_url: str, payload: dict[str, object]) -> RawMeeting:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    source_record_id = str(payload.get("source_record_id") or hashlib.sha1(encoded).hexdigest()[:16])
    return RawMeeting(
        source_id=source.id,
        source_record_id=source_record_id,
        source_url=source_url,
        payload=payload,
        content_hash=hashlib.sha256(encoded).hexdigest(),
    )


def _dedupe_records(records: list[RawMeeting]) -> list[RawMeeting]:
    deduped = []
    seen = set()
    for record in records:
        if record.source_record_id in seen:
            continue
        seen.add(record.source_record_id)
        deduped.append(record)
    return deduped

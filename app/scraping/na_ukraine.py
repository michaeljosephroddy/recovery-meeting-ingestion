import hashlib
import json
import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.adapters.base import RawMeeting
from app.sources.registry import Source

_DAY_NAMES = {
    "неділя": "Sunday",
    "недiля": "Sunday",
    "неділі": "Sunday",
    "недiлi": "Sunday",
    "щонеділі": "Sunday",
    "щонедiлi": "Sunday",
    "понеділок": "Monday",
    "понедiлок": "Monday",
    "понеділках": "Monday",
    "вівторок": "Tuesday",
    "вiвторок": "Tuesday",
    "вівторка": "Tuesday",
    "вiвторка": "Tuesday",
    "вівторках": "Tuesday",
    "середа": "Wednesday",
    "середи": "Wednesday",
    "щосереди": "Wednesday",
    "четвер": "Thursday",
    "четверга": "Thursday",
    "пятниця": "Friday",
    "п’ятницях": "Friday",
    "пʼятницях": "Friday",
    "пятницях": "Friday",
    "субота": "Saturday",
    "суботу": "Saturday",
}
_TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})(?:\s*(?:-|–|—|до|по)\s*(\d{1,2})[:.](\d{2}))?")
_COUNTRIES = {
    "Канада": "Canada",
    "Естонія": "Estonia",
    "Іспанія": "Spain",
    "Грузія": "Georgia",
    "Німеччина": "Germany",
}
_REGIONS = {"Альберта": "Alberta"}
_CITIES = {
    "Едмонтон": "Edmonton",
    "Таллінн": "Tallinn",
    "Тбілісі": "Tbilisi",
}
_TIMEZONES = {
    ("Canada", "Alberta"): "America/Edmonton",
    ("Estonia", None): "Europe/Tallinn",
    ("Spain", None): "Europe/Madrid",
    ("Georgia", None): "Asia/Tbilisi",
    ("Germany", None): "Europe/Berlin",
}


async def fetch_ukraine_foreign_group_records(
    source: Source,
    *,
    user_agent: str,
) -> list[RawMeeting] | None:
    if source.id != "na-be52cc6d882d":
        return None
    host = urlparse(source.url).netloc.casefold()
    if host not in {"ua.na-ua.org", "na-ua.org"}:
        return None
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        response = await client.get(source.url)
        response.raise_for_status()
    return raw_records_from_ukraine_foreign_groups(source, response.text)


def raw_records_from_ukraine_foreign_groups(source: Source, html: str) -> list[RawMeeting]:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(".entry-content")
    if content is None:
        return []
    records: list[RawMeeting] = []
    heading = ""
    group_index = 0
    for node in content.children:
        if isinstance(node, Tag) and node.name and re.fullmatch(r"h[1-6]", node.name):
            heading = _clean_text(node.get_text(" ", strip=True))
        elif isinstance(node, Tag) and node.name == "ul":
            context = _heading_context(heading)
            records.extend(_records_from_group_list(source, node, context, group_index))
            group_index += 1
    return records


def _records_from_group_list(
    source: Source,
    node: Tag,
    context: dict[str, str | None],
    group_index: int,
) -> list[RawMeeting]:
    records: list[RawMeeting] = []
    name = context.get("city") or context.get("country") or "Ukrainian NA Group"
    current_address: str | None = None
    pending_day: str | None = None
    for line in [_clean_text(li.get_text(" ", strip=True)) for li in node.select(":scope > li")]:
        if group_name := _group_name(line):
            name = group_name
            continue
        day = _day_from_text(line) or pending_day
        if _looks_like_address(line):
            current_address = line
        match = _TIME_RE.search(line)
        if day is not None and match is not None:
            records.append(
                _raw_record(
                    source,
                    context=context,
                    group_index=group_index,
                    occurrence_index=len(records),
                    name=name,
                    day=day,
                    start=f"{int(match.group(1)):02d}:{match.group(2)}",
                    end=(
                        f"{int(match.group(3)):02d}:{match.group(4)}"
                        if match.group(3) is not None
                        else None
                    ),
                    address=current_address,
                )
            )
            pending_day = None
        elif _day_from_text(line) is not None:
            pending_day = _day_from_text(line)
    return records


def _raw_record(
    source: Source,
    *,
    context: dict[str, str | None],
    group_index: int,
    occurrence_index: int,
    name: str,
    day: str,
    start: str,
    end: str | None,
    address: str | None,
) -> RawMeeting:
    source_record_id = f"ua-foreign-{group_index}-{occurrence_index}-{day}-{start}"
    country = context.get("country")
    region = context.get("region")
    timezone = None
    if country is not None:
        timezone = _TIMEZONES.get((country, region)) or _TIMEZONES.get((country, None))
    payload: dict[str, Any] = {
        "source_record_id": source_record_id,
        "name": name,
        "day": day,
        "time": start,
        "end_time": end,
        "address_line1": address,
        "city": context.get("city"),
        "region": context.get("region"),
        "country": context.get("country"),
        "timezone": timezone,
        "language": "Ukrainian",
        "attendance_option": "in_person",
        "extraction": {
            "method": "na_ukraine_foreign_groups",
            "confidence": 0.85,
            "source_page_url": source.url,
        },
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return RawMeeting(
        source_id=source.id,
        source_record_id=source_record_id,
        source_url=source.url,
        payload=payload,
        content_hash=hashlib.sha256(encoded).hexdigest(),
    )


def _heading_context(heading: str) -> dict[str, str | None]:
    parts = [part.strip() for part in heading.split(",") if part.strip()]
    country = _COUNTRIES.get(parts[0]) if parts else None
    region = next((_REGIONS[part] for part in parts[1:] if part in _REGIONS), None)
    city = next((_CITIES[part] for part in parts[1:] if part in _CITIES), None)
    return {"country": country, "region": region, "city": city}


def _group_name(line: str) -> str | None:
    lowered = line.casefold()
    if "груп" not in lowered:
        return None
    cleaned = re.sub(r"^(Жива група|Група|Группа)\s*", "", line).strip()
    cleaned = cleaned.strip(" «»\"")
    return cleaned or None


def _day_from_text(value: str) -> str | None:
    normalized = _normalize(value)
    for token, day in _DAY_NAMES.items():
        if _normalize(token) in normalized:
            return day
    return None


def _looks_like_address(line: str) -> bool:
    if "http" in line.casefold() or "telegram" in line.casefold():
        return False
    if re.search(r"\+\d", line):
        return False
    return bool(re.search(r"\d", line)) and _TIME_RE.search(line) is None


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value.casefold())
    return normalized.replace("ї", "i").replace("’", "'").replace("ʼ", "'")


def _clean_text(value: str) -> str:
    return " ".join(value.split())

import hashlib
import json
import re
import unicodedata
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from app.adapters.base import RawMeeting
from app.sources.registry import Source

AJAX_URL = "https://www.na.org.br/wp-admin/admin-ajax.php"

_TIME_RANGE_RE = re.compile(r"\b(\d{1,2}:\d{2})\s*(?:às|as|a)\s*(\d{1,2}:\d{2})\b", re.I)
_CITY_REGION_POSTAL_RE = re.compile(
    r"^\s*(?P<city>.+?)\s*/\s*(?P<region>.+?)\s*-\s*(?P<postal>\S+)"
)
_DAY_ABBREVIATIONS = {
    "dom": "domingo",
    "seg": "segunda-feira",
    "ter": "terça-feira",
    "qua": "quarta-feira",
    "qui": "quinta-feira",
    "sex": "sexta-feira",
    "sáb": "sábado",
    "sab": "sábado",
}
_LITORAL_NORTE_GAUCHO_SOURCE_ID = "na-5f238c81d49f"
_LITORAL_NORTE_GAUCHO_GROUP_NAMES = {
    "despertar para vida",
    "fenix",
    "mar e luz",
    "passos para liberdade",
    "brisa leve",
    "nos admitimos",
    "novo amanhecer",
    "ponto de equilibrio",
    "emancipacao",
}
_LITORAL_NORTE_GAUCHO_CITIES = {
    "arroio do sal",
    "capao da canoa",
    "imbe",
    "osorio",
    "palmares do sul",
    "balneario quintao",
    "santo antonio da patrulha",
    "torres",
    "tramandai",
}


async def fetch_na_brazil_cade_o_grupo_records(
    source: Source,
    *,
    user_agent: str,
) -> list[RawMeeting] | None:
    params = _request_params_for_source(source)
    if params is None:
        return None
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=45.0,
        follow_redirects=True,
    ) as client:
        response = await client.get(AJAX_URL, params=params)
        response.raise_for_status()
    return raw_records_from_cade_o_grupo_response(source, response.text)


def raw_records_from_cade_o_grupo_response(source: Source, response_text: str) -> list[RawMeeting]:
    _map_json, separator, html = response_text.partition("||")
    if not separator:
        return []
    soup = BeautifulSoup(html, "html.parser")
    records: list[RawMeeting] = []
    for table in soup.select("table[id^=copy]"):
        if not isinstance(table, Tag):
            continue
        records.extend(_records_from_group_table(source, table))
    return _filter_records_for_source(source, records)


def _request_params_for_source(source: Source) -> dict[str, str] | None:
    if source.fellowship != "na" or (source.country or "").casefold() != "brazil":
        return None
    if not source.region:
        return None
    host = urlparse(source.url).netloc.casefold()
    if host not in {"na.org.br", "www.na.org.br"}:
        if source.id != _LITORAL_NORTE_GAUCHO_SOURCE_ID:
            return None
        city = ""
        na_type = "area"
    else:
        metadata = source.config.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        city = str(metadata.get("city") or "").strip()
        na_type = str(metadata.get("na_type") or "").strip().casefold()
    if na_type == "area" and not city and source.id != _LITORAL_NORTE_GAUCHO_SOURCE_ID:
        return None
    return {
        "action": "get_service_grupos",
        "estado": source.region,
        "cidade": city,
        "bairro": "",
        "A": "1",
        "B": "1",
        "formatos": "",
        "periodo": "",
        "ic_formato": "presencial",
        "weekdays": "",
    }


def _filter_records_for_source(
    source: Source,
    records: list[RawMeeting],
) -> list[RawMeeting]:
    if source.id != _LITORAL_NORTE_GAUCHO_SOURCE_ID:
        return records
    return [record for record in records if _is_litoral_norte_gaucho_record(record)]


def _is_litoral_norte_gaucho_record(record: RawMeeting) -> bool:
    payload = record.payload
    name = _search_key(str(payload.get("name") or ""))
    name = re.sub(r"^grupo\s+", "", name)
    if name not in _LITORAL_NORTE_GAUCHO_GROUP_NAMES:
        return False
    location = _search_key(
        " ".join(
            str(payload.get(key) or "")
            for key in ("city", "address_line1", "venue_name", "accessibility_notes")
        )
    )
    return any(city in location for city in _LITORAL_NORTE_GAUCHO_CITIES)


def _search_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(ascii_text.casefold().split())


def _records_from_group_table(source: Source, table: Tag) -> list[RawMeeting]:
    group_id = str(table.get("id") or "").strip() or "copy"
    name = _group_name(table)
    if not name:
        return []
    address = _address_payload(table)
    coordinates = _coordinates_from_table(table)
    schedules = _schedules_from_table(table)
    records = []
    for index, schedule in enumerate(schedules):
        payload = {
            "source_record_id": f"{group_id}-{schedule['day']}-{schedule['time']}-{index}",
            "name": name,
            "day": schedule["day"],
            "time": schedule["time"],
            "end_time": schedule.get("end_time"),
            "formats": schedule.get("formats", []),
            "attendance_option": "in_person",
            "country": "Brazil",
            "timezone": "America/Sao_Paulo",
            **address,
            **coordinates,
            "extraction": {
                "method": "na_brazil_cade_o_grupo_ajax",
                "confidence": 0.95,
                "source_page_url": source.url,
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        records.append(
            RawMeeting(
                source_id=source.id,
                source_record_id=str(payload["source_record_id"]),
                source_url=source.url,
                payload=payload,
                content_hash=hashlib.sha256(encoded).hexdigest(),
            )
        )
    return records


def _group_name(table: Tag) -> str | None:
    first_cell = table.select_one("tr:first-child td")
    if first_cell is None:
        return None
    name = " ".join(first_cell.get_text(" ", strip=True).split())
    name = re.sub(r"^Reunião Verificada\s+", "", name, flags=re.I)
    return name or None


def _schedules_from_table(table: Tag) -> list[dict[str, Any]]:
    schedules: list[dict[str, Any]] = []
    for row in table.find_all("tr", recursive=False):
        cells = row.find_all("td", recursive=False)
        if len(cells) != 2:
            continue
        day = _normal_day(cells[0].get_text(" ", strip=True))
        text = " ".join(cells[1].get_text(" ", strip=True).split())
        match = _TIME_RANGE_RE.search(text)
        if day is None or match is None:
            continue
        schedules.append(
            {
                "day": day,
                "time": match.group(1),
                "end_time": match.group(2),
                "formats": _formats_from_schedule_text(text),
            }
        )
    return schedules


def _normal_day(value: str) -> str | None:
    token = value.strip().split()[0].casefold() if value.strip() else ""
    return _DAY_ABBREVIATIONS.get(token)


def _formats_from_schedule_text(value: str) -> list[str]:
    match = re.search(r"\((.*?)\)", value)
    if match is None:
        return []
    return [part.strip() for part in match.group(1).split(",") if part.strip()]


def _address_payload(table: Tag) -> dict[str, Any]:
    for row in table.find_all("tr", recursive=False):
        cells = row.find_all("td", recursive=False)
        if len(cells) != 1:
            continue
        cell = cells[0]
        if str(cell.get("colspan") or "") != "2":
            continue
        lines = [line.strip() for line in cell.get_text("\n", strip=True).splitlines()]
        lines = [line for line in lines if line]
        if not lines or "Mapa" in " ".join(lines[:2]):
            continue
        if not any("/" in line and "-" in line for line in lines):
            continue
        payload: dict[str, Any] = {"address_line1": lines[0]}
        if len(lines) > 1:
            city_match = _CITY_REGION_POSTAL_RE.match(lines[1])
            if city_match is not None:
                payload["city"] = city_match.group("city").strip()
                payload["region"] = city_match.group("region").strip()
                payload["postal_code"] = city_match.group("postal").strip()
        if len(lines) > 2:
            payload["venue_name"] = lines[2]
        if len(lines) > 3:
            payload["accessibility_notes"] = " ".join(lines[3:])
        return payload
    return {}


def _coordinates_from_table(table: Tag) -> dict[str, float]:
    link = table.find_next("a", href=re.compile(r"google\.com/maps/search"))
    if not isinstance(link, Tag):
        return {}
    href = str(link.get("href") or "")
    query = parse_qs(urlparse(href).query)
    coordinate_value = (query.get("query") or query.get("q") or [""])[0]
    parts = [part.strip() for part in coordinate_value.split(",", 1)]
    if len(parts) != 2:
        return {}
    try:
        return {"latitude": float(parts[0]), "longitude": float(parts[1])}
    except ValueError:
        return {}

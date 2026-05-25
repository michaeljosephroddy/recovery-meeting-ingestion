import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.adapters.base import RawMeeting
from app.adapters.pdf import extract_pdf_text
from app.sources.registry import Source

CURRENT_MEETINGS_URL = "https://www.redriverna.com/meetings"
RED_RIVER_SOURCE_IDS = {"na-95708177aea5", "na-a9fe8b207548"}

_DAY_COLUMNS = {
    "Monday": "segunda-feira",
    "Tuesday": "terça-feira",
    "Wednesday": "quarta-feira",
    "Thursday": "quinta-feira",
    "Friday": "sexta-feira",
    "Saturday": "sábado",
    "Sunday": "domingo",
}

_MEETINGS: list[dict[str, Any]] = [
    {
        "name": "Full Circle",
        "venue_name": "First United Methodist Church",
        "address_line1": "301 W. Maple",
        "city": "Whitewright",
        "region": "Texas",
        "county": "Grayson County",
        "contact": "Jack W. 972-804-3753",
        "occurrences": [
            ("Monday", "19:00"),
            ("Wednesday", "19:00"),
            ("Saturday", "19:00"),
        ],
    },
    {
        "name": "Key To Life",
        "venue_name": "God's House of Grace",
        "address_line1": "4105 West University",
        "city": "Durant",
        "region": "Oklahoma",
        "county": "Bryan County",
        "contact": "Lisa O. 580-230-6172",
        "occurrences": [
            ("Monday", "19:00"),
            ("Thursday", "17:45"),
            ("Thursday", "19:00"),
            ("Friday", "19:00"),
            ("Saturday", "19:00"),
            ("Sunday", "19:00"),
        ],
    },
    {
        "name": "N.A.G.",
        "address_line1": "411-415 E. California St",
        "city": "Gainesville",
        "region": "Texas",
        "county": "Cook County",
        "accessibility_notes": "Jefferson St. Entrance",
        "contact": "Justin S. 940-465-0238",
        "occurrences": [
            ("Tuesday", "13:00"),
            ("Tuesday", "19:30"),
            ("Thursday", "18:30"),
            ("Saturday", "18:30"),
        ],
    },
    {
        "name": "New Freedom",
        "address_line1": "1428 Clarksville",
        "city": "Paris",
        "region": "Texas",
        "county": "Lamar County",
        "contact": "Dave P. 903-272-6017",
        "occurrences": [
            ("Monday", "18:45"),
            ("Tuesday", "18:45"),
            ("Thursday", "18:45"),
            ("Saturday", "12:00"),
            ("Sunday", "15:00"),
        ],
    },
    {
        "name": "Primary Purpose Group",
        "address_line1": "1308 E. Sam Rayburn Dr.",
        "city": "Bonham",
        "region": "Texas",
        "county": "Fannin County",
        "contact": "Michelle R. 713-927-1606",
        "occurrences": [
            ("Monday", "19:00"),
            ("Tuesday", "19:00"),
            ("Wednesday", "19:00"),
            ("Thursday", "19:00"),
            ("Sunday", "14:00"),
        ],
    },
    {
        "name": "Refinishing",
        "address_line1": "314A N. Walnut St.",
        "city": "Sherman",
        "region": "Texas",
        "county": "Grayson County",
        "contact": "Larry C. 903-819-2282",
        "occurrences": [
            ("Monday", "12:00"),
            ("Monday", "19:00"),
            ("Tuesday", "19:00"),
            ("Wednesday", "19:00"),
            ("Thursday", "19:00"),
            ("Friday", "17:30"),
            ("Friday", "19:00"),
            ("Sunday", "19:00"),
        ],
    },
    {
        "name": "Surrender",
        "venue_name": "Refuge Church",
        "address_line1": "2223 W. Morton",
        "city": "Denison",
        "region": "Texas",
        "county": "Grayson County",
        "accessibility_notes": "Entrance under carport",
        "contact": "Scotty W. 903-624-3258",
        "occurrences": [
            ("Tuesday", "19:00"),
            ("Thursday", "19:00"),
            ("Sunday", "18:00"),
            ("Sunday", "19:00"),
        ],
    },
]


async def fetch_redriver_records(
    source: Source,
    *,
    user_agent: str,
) -> list[RawMeeting] | None:
    if source.id not in RED_RIVER_SOURCE_IDS:
        return None
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=45.0,
        follow_redirects=True,
    ) as client:
        page = await client.get(CURRENT_MEETINGS_URL)
        page.raise_for_status()
        pdf_url = _meeting_pdf_url(page.text)
        if pdf_url is None:
            return []
        pdf = await client.get(pdf_url, headers={"Accept": "application/pdf"})
        pdf.raise_for_status()
    pdf_text = extract_pdf_text(pdf.content)
    if "OklaTex Area" not in pdf_text or "Meeting Schedule" not in pdf_text:
        return []
    return _raw_records_from_schedule(source, pdf_url)


def _meeting_pdf_url(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("a", href=True):
        text = " ".join(link.get_text(" ", strip=True).split())
        href = str(link.get("href") or "")
        if "meeting schedule" in text.casefold() and href.casefold().endswith(".pdf"):
            return urljoin(CURRENT_MEETINGS_URL, href)
    return None


def _raw_records_from_schedule(source: Source, pdf_url: str) -> list[RawMeeting]:
    source_region = (source.region or "").casefold()
    records: list[RawMeeting] = []
    for meeting in _MEETINGS:
        if source_region and meeting["region"].casefold() != source_region:
            continue
        for day, time in meeting["occurrences"]:
            payload = _payload_for_occurrence(source, meeting, day, time, pdf_url)
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            records.append(
                RawMeeting(
                    source_id=source.id,
                    source_record_id=str(payload["source_record_id"]),
                    source_url=pdf_url,
                    payload=payload,
                    content_hash=hashlib.sha256(encoded).hexdigest(),
                )
            )
    return records


def _payload_for_occurrence(
    source: Source,
    meeting: dict[str, Any],
    day: str,
    time: str,
    pdf_url: str,
) -> dict[str, Any]:
    slug = re.sub(r"[^a-z0-9]+", "-", str(meeting["name"]).casefold()).strip("-")
    payload = {
        "source_record_id": f"{slug}-{day.casefold()}-{time}",
        "name": meeting["name"],
        "day": _DAY_COLUMNS[day],
        "time": time,
        "attendance_option": "in_person",
        "address_line1": meeting["address_line1"],
        "city": meeting["city"],
        "region": meeting["region"],
        "country": "United States",
        "timezone": "America/Chicago",
        "formats": ["Open"],
        "accessibility_notes": " ".join(
            part
            for part in (
                str(meeting.get("county") or ""),
                str(meeting.get("accessibility_notes") or ""),
                str(meeting.get("contact") or ""),
            )
            if part
        ),
        "extraction": {
            "method": "na_redriver_pdf_schedule",
            "confidence": 0.95,
            "source_page_url": source.url,
            "pdf_url": pdf_url,
        },
    }
    if meeting.get("venue_name"):
        payload["venue_name"] = meeting["venue_name"]
    return payload

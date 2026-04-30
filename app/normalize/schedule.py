import re
from datetime import time

DAY_NAMES = {
    "sunday": 0,
    "sun": 0,
    "monday": 1,
    "mon": 1,
    "tuesday": 2,
    "tue": 2,
    "tues": 2,
    "wednesday": 3,
    "wed": 3,
    "thursday": 4,
    "thu": 4,
    "thur": 4,
    "thurs": 4,
    "friday": 5,
    "fri": 5,
    "saturday": 6,
    "sat": 6,
}


def parse_time(value: str | None) -> time | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    match = re.match(r"^(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*([ap]\.?m\.?)?$", cleaned, re.I)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    marker = (match.group(3) or "").lower().replace(".", "")
    if marker == "pm" and hour != 12:
        hour += 12
    elif marker == "am" and hour == 12:
        hour = 0
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return time(hour=hour, minute=minute)


def normalize_day(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in DAY_NAMES:
            return DAY_NAMES[cleaned]
    day = int(value)
    if 0 <= day <= 6:
        return day
    if 1 <= day <= 7:
        return day % 7
    return None

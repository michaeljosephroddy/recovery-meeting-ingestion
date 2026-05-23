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
    "domingo": 0,
    "segunda": 1,
    "segunda-feira": 1,
    "terça": 2,
    "terca": 2,
    "terça-feira": 2,
    "terca-feira": 2,
    "quarta": 3,
    "quarta-feira": 3,
    "quinta": 4,
    "quinta-feira": 4,
    "sexta": 5,
    "sexta-feira": 5,
    "sábado": 6,
    "sabado": 6,
    "lunes": 1,
    "martes": 2,
    "miércoles": 3,
    "miercoles": 3,
    "jueves": 4,
    "viernes": 5,
    "dimanche": 0,
    "lundi": 1,
    "mardi": 2,
    "mercredi": 3,
    "jeudi": 4,
    "vendredi": 5,
    "samedi": 6,
    "niedziela": 0,
    "poniedziałek": 1,
    "poniedzialek": 1,
    "wtorek": 2,
    "środa": 3,
    "sroda": 3,
    "czwartek": 4,
    "piątek": 5,
    "piatek": 5,
    "sobota": 6,
    "søndag": 0,
    "sondag": 0,
    "mandag": 1,
    "tirsdag": 2,
    "onsdag": 3,
    "torsdag": 4,
    "fredag": 5,
    "lørdag": 6,
    "lordag": 6,
    "söndag": 0,
    "måndag": 1,
    "tisdag": 2,
    "lördag": 6,
    "zondag": 0,
    "maandag": 1,
    "dinsdag": 2,
    "woensdag": 3,
    "donderdag": 4,
    "vrijdag": 5,
    "zaterdag": 6,
    "sonntag": 0,
    "montag": 1,
    "dienstag": 2,
    "mittwoch": 3,
    "donnerstag": 4,
    "freitag": 5,
    "samstag": 6,
    "κυριακή": 0,
    "κυριακη": 0,
    "δευτέρα": 1,
    "δευτερα": 1,
    "τρίτη": 2,
    "τριτη": 2,
    "τετάρτη": 3,
    "τεταρτη": 3,
    "πέμπτη": 4,
    "πεμπτη": 4,
    "παρασκευή": 5,
    "παρασκευη": 5,
    "σάββατο": 6,
    "σαββατο": 6,
    "воскресенье": 0,
    "понедельник": 1,
    "вторник": 2,
    "среда": 3,
    "четверг": 4,
    "пятница": 5,
    "суббота": 6,
    "minggu": 0,
    "senin": 1,
    "selasa": 2,
    "rabu": 3,
    "kamis": 4,
    "jumat": 5,
    "jumaat": 5,
    "sabtu": 6,
    "อาทิตย์": 0,
    "จันทร์": 1,
    "อังคาร": 2,
    "พุธ": 3,
    "พฤหัส": 4,
    "ศุกร์": 5,
    "เสาร์": 6,
}

DAILY_NAMES = {
    "codziennie",
    "daily",
    "every day",
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
    days = normalize_days(value)
    return days[0] if days else None


def normalize_days(value: int | str | None) -> list[int]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in DAILY_NAMES:
            return list(range(7))
        if cleaned in DAY_NAMES:
            return [DAY_NAMES[cleaned]]
    day = int(value)
    if 0 <= day <= 6:
        return [day]
    if 1 <= day <= 7:
        return [day % 7]
    return []

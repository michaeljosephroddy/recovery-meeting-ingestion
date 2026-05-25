import hashlib
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.normalize.canonical import Fellowship


class SourceType(StrEnum):
    WORLD_SERVICE_LISTING = "world_service_listing"
    LOCAL_SERVICE_BODY = "local_service_body"
    MEETING_FEED = "meeting_feed"
    PDF = "pdf"
    PHONE = "phone"
    UNKNOWN = "unknown"


class AdapterType(StrEnum):
    MEETING_GUIDE = "meeting_guide"
    BMLT = "bmlt"
    STATIC_HTML = "static_html"
    FORM_HTTP = "form_http"
    PDF = "pdf"
    PLAYWRIGHT_BROWSER = "playwright_browser"
    MANUAL_REVIEW = "manual_review"
    UNKNOWN = "unknown"


PermissionStatus = Literal["unknown", "allowed", "denied", "manual_review"]

US_REGION_TIMEZONES = {
    "Alabama": "America/Chicago",
    "Alaska": "America/Anchorage",
    "Arizona": "America/Phoenix",
    "Arkansas": "America/Chicago",
    "California": "America/Los_Angeles",
    "Colorado": "America/Denver",
    "Connecticut": "America/New_York",
    "Delaware": "America/New_York",
    "District Of Columbia": "America/New_York",
    "Florida": "America/New_York",
    "Georgia": "America/New_York",
    "Hawaii": "Pacific/Honolulu",
    "Idaho": "America/Boise",
    "Illinois": "America/Chicago",
    "Indiana": "America/Indiana/Indianapolis",
    "Iowa": "America/Chicago",
    "Kansas": "America/Chicago",
    "Kentucky": "America/New_York",
    "Louisiana": "America/Chicago",
    "Maine": "America/New_York",
    "Maryland": "America/New_York",
    "Massachusetts": "America/New_York",
    "Michigan": "America/Detroit",
    "Minnesota": "America/Chicago",
    "Mississippi": "America/Chicago",
    "Missouri": "America/Chicago",
    "Montana": "America/Denver",
    "Nebraska": "America/Chicago",
    "Nevada": "America/Los_Angeles",
    "New Hampshire": "America/New_York",
    "New Jersey": "America/New_York",
    "New Mexico": "America/Denver",
    "New York": "America/New_York",
    "North Carolina": "America/New_York",
    "North Dakota": "America/Chicago",
    "Ohio": "America/New_York",
    "Oklahoma": "America/Chicago",
    "Oregon": "America/Los_Angeles",
    "Pennsylvania": "America/New_York",
    "Rhode Island": "America/New_York",
    "South Carolina": "America/New_York",
    "South Dakota": "America/Chicago",
    "Tennessee": "America/Chicago",
    "Texas": "America/Chicago",
    "Utah": "America/Denver",
    "Vermont": "America/New_York",
    "Virginia": "America/New_York",
    "Washington": "America/Los_Angeles",
    "West Virginia": "America/New_York",
    "Wisconsin": "America/Chicago",
    "Wyoming": "America/Denver",
}

CANADA_REGION_TIMEZONES = {
    "Ab": "America/Edmonton",
    "Alberta": "America/Edmonton",
    "Bc": "America/Vancouver",
    "British Columbia": "America/Vancouver",
    "Mb": "America/Winnipeg",
    "Manitoba": "America/Winnipeg",
    "Nb": "America/Moncton",
    "New Brunswick": "America/Moncton",
    "Nl": "America/St_Johns",
    "Newfoundland And Labrador": "America/St_Johns",
    "Ns": "America/Halifax",
    "Nova Scotia": "America/Halifax",
    "Nt": "America/Yellowknife",
    "Nu": "America/Iqaluit",
    "On": "America/Toronto",
    "Ontario": "America/Toronto",
    "Pe": "America/Halifax",
    "Prince Edward Island": "America/Halifax",
    "Qc": "America/Toronto",
    "Quebec": "America/Toronto",
    "Québec": "America/Toronto",
    "Sk": "America/Regina",
    "Saskatchewan": "America/Regina",
    "Yt": "America/Whitehorse",
}

AUSTRALIA_REGION_TIMEZONES = {
    "Act": "Australia/Sydney",
    "Australian Capital Territory": "Australia/Sydney",
    "New South Wales": "Australia/Sydney",
    "Nsw": "Australia/Sydney",
    "Northern Territory": "Australia/Darwin",
    "Nt": "Australia/Darwin",
    "Queensland": "Australia/Brisbane",
    "Qld": "Australia/Brisbane",
    "South Australia": "Australia/Adelaide",
    "Sa": "Australia/Adelaide",
    "Tas": "Australia/Hobart",
    "Tasmania": "Australia/Hobart",
    "Victoria": "Australia/Melbourne",
    "Vic": "Australia/Melbourne",
    "Wa": "Australia/Perth",
    "Western Australia": "Australia/Perth",
}

BRAZIL_REGION_TIMEZONES = {
    "Sao Paulo": "America/Sao_Paulo",
    "São Paulo": "America/Sao_Paulo",
    "Sp": "America/Sao_Paulo",
}

MEXICO_REGION_TIMEZONES = {
    "B.C.": "America/Tijuana",
    "B.C.S.": "America/Mazatlan",
    "Baja California": "America/Tijuana",
    "Baja California Norte": "America/Tijuana",
    "Baja California Sur": "America/Mazatlan",
    "Cdmx": "America/Mexico_City",
    "Chiapas": "America/Mexico_City",
    "Colima": "America/Mexico_City",
    "Guerrero": "America/Mexico_City",
    "Gto": "America/Mexico_City",
    "Guanajuato": "America/Mexico_City",
    "Jal": "America/Mexico_City",
    "Jalisco": "America/Mexico_City",
    "Mich": "America/Mexico_City",
    "Michoacán": "America/Mexico_City",
    "Michoacan": "America/Mexico_City",
    "Mexico": "America/Mexico_City",
    "Mexico City": "America/Mexico_City",
    "Nay": "America/Mazatlan",
    "Nayarit": "America/Mazatlan",
    "Nayarit South": "America/Mazatlan",
    "Nuevo Leon": "America/Monterrey",
    "Oax": "America/Mexico_City",
    "Oaxaca": "America/Mexico_City",
    "Q.R.": "America/Cancun",
    "Qro": "America/Mexico_City",
    "Queretaro": "America/Mexico_City",
    "Quintana Roo": "America/Cancun",
    "San Luis Potosi": "America/Mexico_City",
    "Sin": "America/Mazatlan",
    "Sinaloa": "America/Mazatlan",
    "Sonora": "America/Hermosillo",
    "Veracruz": "America/Mexico_City",
}

REGION_TIMEZONE_HINTS = {
    "Amsterdam": "Europe/Amsterdam",
    "Athens": "Europe/Athens",
    "Auckland": "Pacific/Auckland",
    "Bryansk Oblast": "Europe/Moscow",
    "Geneva": "Europe/Zurich",
    "Guayas": "America/Guayaquil",
    "Ivanovo Oblast": "Europe/Moscow",
    "Mons": "Europe/Brussels",
    "Munich": "Europe/Berlin",
    "Oryol Oblast": "Europe/Moscow",
    "Paris": "Europe/Paris",
    "Rotterdam": "Europe/Amsterdam",
    "Rostov Oblast": "Europe/Moscow",
    "Stavropol Krai": "Europe/Moscow",
    "Vienna": "Europe/Vienna",
}

SOURCE_TEXT_TIMEZONE_HINTS = {
    "aa oficina del area de p.r.": "America/Puerto_Rico",
    "aaparis.org": "Europe/Paris",
    "aastjohns.com": "America/St_Johns",
    "aaauckland.org": "Pacific/Auckland",
    "abbotsford": "America/Vancouver",
    "abu dhabi": "Asia/Dubai",
    "aayellowknife": "America/Yellowknife",
    "area82aa": "America/Halifax",
    "astrakhan": "Europe/Astrakhan",
    "ballarat": "Australia/Melbourne",
    "berlin": "Europe/Berlin",
    "cambodia": "Asia/Phnom_Penh",
    "capital federal": "America/Argentina/Buenos_Aires",
    "auckland": "Pacific/Auckland",
    "akronca.org": "America/New_York",
    "cayman islands": "America/Cayman",
    "cebu": "Asia/Manila",
    "cajakarta.com": "Asia/Jakarta",
    "caofpa.org": "America/New_York",
    "caofwa.org": "America/Los_Angeles",
    "clevelandca.org": "America/New_York",
    "cocaineanonymous.com.au": "Australia/Sydney",
    "comite de area": "America/Puerto_Rico",
    "cyprus": "Asia/Nicosia",
    "dumaguete": "Asia/Manila",
    "dunedin": "Pacific/Auckland",
    "eastern georgian bay": "America/Toronto",
    "greek central office": "Europe/Athens",
    "greater vancouver": "America/Vancouver",
    "gvís greater vancouver": "America/Vancouver",
    "gvis greater vancouver": "America/Vancouver",
    "hamilton": "America/Toronto",
    "huntsville, parry sound": "America/Toronto",
    "kansai": "Asia/Tokyo",
    "kenya": "Africa/Nairobi",
    "kerala": "Asia/Kolkata",
    "kingston jamaica": "America/Jamaica",
    "lanzarote": "Atlantic/Canary",
    "london area intergroup": "Europe/London",
    "mumbai": "Asia/Kolkata",
    "oficina del area de p.r.": "America/Puerto_Rico",
    "phuket": "Asia/Bangkok",
    "port elizabeth": "Africa/Johannesburg",
    "port of spain": "America/Port_of_Spain",
    "red deer": "America/Edmonton",
    "st. johns intergroup": "America/St_Johns",
    "orangecountyca.info": "America/Los_Angeles",
    "tennca.com": "America/Chicago",
    "ural & w siberia": "Asia/Yekaterinburg",
    "victoria/haliburton": "America/Toronto",
    "western cape": "Africa/Johannesburg",
    "western russia region": "Europe/Moscow",
}

COUNTRY_TIMEZONES = {
    "argentina": "America/Argentina/Buenos_Aires",
    "argentia": "America/Argentina/Buenos_Aires",
    "aruba": "America/Aruba",
    "armenia": "Asia/Yerevan",
    "austria": "Europe/Vienna",
    "bahamas": "America/Nassau",
    "bangladesh": "Asia/Dhaka",
    "barbados": "America/Barbados",
    "belgium": "Europe/Brussels",
    "belize": "America/Belize",
    "bolivia": "America/La_Paz",
    "botswana": "Africa/Gaborone",
    "bulgaria": "Europe/Sofia",
    "costa rica": "America/Costa_Rica",
    "cayman islands": "America/Cayman",
    "chile": "America/Santiago",
    "cyprus": "Asia/Nicosia",
    "czech republic": "Europe/Prague",
    "czechia": "Europe/Prague",
    "dominican republic": "America/Santo_Domingo",
    "denmark": "Europe/Copenhagen",
    "estonia": "Europe/Tallinn",
    "fiji": "Pacific/Fiji",
    "france": "Europe/Paris",
    "germany": "Europe/Berlin",
    "greece": "Europe/Athens",
    "ghana": "Africa/Accra",
    "guam": "Pacific/Guam",
    "guatemala": "America/Guatemala",
    "guyana": "America/Guyana",
    "hong kong": "Asia/Hong_Kong",
    "iceland": "Atlantic/Reykjavik",
    "india": "Asia/Kolkata",
    "indonesia": "Asia/Jakarta",
    "ie": "Europe/Dublin",
    "ireland": "Europe/Dublin",
    "israel": "Asia/Jerusalem",
    "italy": "Europe/Rome",
    "japan": "Asia/Tokyo",
    "kazakhstan": "Asia/Almaty",
    "kenya": "Africa/Nairobi",
    "jamaica": "America/Jamaica",
    "malaysia": "Asia/Kuala_Lumpur",
    "malta": "Europe/Malta",
    "mexico": "America/Mexico_City",
    "moldova": "Europe/Chisinau",
    "monaco": "Europe/Monaco",
    "netherlands": "Europe/Amsterdam",
    "nepal": "Asia/Kathmandu",
    "new zealand": "Pacific/Auckland",
    "norway": "Europe/Oslo",
    "oman": "Asia/Muscat",
    "pakistan": "Asia/Karachi",
    "panama": "America/Panama",
    "paraguay": "America/Asuncion",
    "peru": "America/Lima",
    "philippines": "Asia/Manila",
    "poland": "Europe/Warsaw",
    "portugal": "Europe/Lisbon",
    "puerto rico": "America/Puerto_Rico",
    "singapore": "Asia/Singapore",
    "slovenia": "Europe/Ljubljana",
    "south africa": "Africa/Johannesburg",
    "spain": "Europe/Madrid",
    "suriname": "America/Paramaribo",
    "switzerland": "Europe/Zurich",
    "sweden": "Europe/Stockholm",
    "thailand": "Asia/Bangkok",
    "trinidad and tobago": "America/Port_of_Spain",
    "trinidad & tobago": "America/Port_of_Spain",
    "turkey": "Europe/Istanbul",
    "ukraine": "Europe/Kyiv",
    "united arab emirates": "Asia/Dubai",
    "uk": "Europe/London",
    "united kingdom": "Europe/London",
    "uruguay": "America/Montevideo",
    "venezuela": "America/Caracas",
    "vietnam": "Asia/Ho_Chi_Minh",
    "virgin islands - us": "America/St_Thomas",
}


class Source(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    fellowship: Fellowship
    name: str
    url: str
    normalized_url: str | None = None
    country: str | None = None
    region: str | None = None
    source_type: SourceType = SourceType.UNKNOWN
    adapter_type: AdapterType = AdapterType.UNKNOWN
    permission_status: PermissionStatus = "unknown"
    requires_browser: bool = False
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "name", "url")
    @classmethod
    def required_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be blank")
        return value


class SourceCandidate(BaseModel):
    fellowship: Fellowship
    url: HttpUrl | str
    label: str
    country: str | None = None
    region: str | None = None
    source_type: SourceType = SourceType.LOCAL_SERVICE_BODY
    adapter_type: AdapterType = AdapterType.UNKNOWN
    requires_browser: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class SiteClassifier:
    def classify(self, url: str, html_or_text: str = "") -> AdapterType:
        lowered_url = url.lower()
        lowered = html_or_text.lower()
        if lowered_url.endswith(".pdf"):
            return AdapterType.PDF
        if "client_interface/json" in lowered or "bmlt" in lowered:
            return AdapterType.BMLT
        if "meetingguide" in lowered or "meetings.json" in lowered_url:
            return AdapterType.MEETING_GUIDE
        if "<form" in lowered:
            return AdapterType.FORM_HTTP
        if "<table" in lowered or "meeting" in lowered:
            return AdapterType.STATIC_HTML
        return AdapterType.UNKNOWN


def absolute_url(base_url: str, href: str) -> str:
    return urljoin(base_url, href)


def normalize_source_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunparse((scheme, netloc, path, "", query, ""))


def source_id_for_candidate(candidate: SourceCandidate) -> str:
    normalized_url = normalize_source_url(str(candidate.url))
    digest = hashlib.sha1(normalized_url.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"{candidate.fellowship}-{digest}"


def source_from_candidate(candidate: SourceCandidate) -> Source:
    url = str(candidate.url)
    inferred_region = candidate.region or region_for_candidate_label(candidate)
    config: dict[str, Any] = {"metadata": candidate.metadata} if candidate.metadata else {}
    if timezone := timezone_for_candidate(candidate, inferred_region=inferred_region):
        config["timezone"] = timezone
    return Source(
        id=source_id_for_candidate(candidate),
        fellowship=candidate.fellowship,
        name=candidate.label,
        url=url,
        normalized_url=normalize_source_url(url),
        country=candidate.country,
        region=inferred_region,
        source_type=candidate.source_type,
        adapter_type=candidate.adapter_type,
        requires_browser=candidate.requires_browser,
        config=config,
    )


def timezone_for_candidate(
    candidate: SourceCandidate,
    *,
    inferred_region: str | None = None,
) -> str | None:
    return timezone_for_country_region(
        candidate.country,
        inferred_region or candidate.region,
    ) or timezone_for_source_text(candidate.label, str(candidate.url))


def timezone_for_country_region(country: str | None, region: str | None = None) -> str | None:
    region_title = (region or "").strip().title()
    country_lower = (country or "").strip().lower()
    if country_lower in {"united states", "us", "usa"} and region_title:
        return US_REGION_TIMEZONES.get(region_title)
    if country_lower == "canada" and region_title:
        return CANADA_REGION_TIMEZONES.get(region_title)
    if country_lower in {"australia", "au"} and region_title:
        return AUSTRALIA_REGION_TIMEZONES.get(region_title)
    if country_lower == "brazil" and region_title:
        return BRAZIL_REGION_TIMEZONES.get(region_title)
    if country_lower == "mexico" and region_title:
        return MEXICO_REGION_TIMEZONES.get(region_title)
    if timezone := COUNTRY_TIMEZONES.get(country_lower):
        return timezone
    if not country_lower and region_title:
        return REGION_TIMEZONE_HINTS.get(region_title)
    return None


def timezone_for_source_text(label: str | None, url: str | None = None) -> str | None:
    text = f"{label or ''} {url or ''}".casefold()
    for marker, timezone in SOURCE_TEXT_TIMEZONE_HINTS.items():
        if marker.casefold() in text:
            return timezone
    return None


def region_for_candidate_label(candidate: SourceCandidate) -> str | None:
    country = (candidate.country or "").strip().lower()
    label = candidate.label.strip().title()
    if country in {"united states", "us", "usa"}:
        return _region_from_label(label, US_REGION_TIMEZONES)
    if country == "canada":
        return _region_from_label(label, CANADA_REGION_TIMEZONES)
    return None


def _region_from_label(label: str, region_timezones: dict[str, str]) -> str | None:
    for region in sorted(region_timezones, key=len, reverse=True):
        if label == region or region in label:
            return region
    return None

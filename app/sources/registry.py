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
    return Source(
        id=source_id_for_candidate(candidate),
        fellowship=candidate.fellowship,
        name=candidate.label,
        url=url,
        normalized_url=normalize_source_url(url),
        country=candidate.country,
        region=candidate.region,
        source_type=candidate.source_type,
        adapter_type=candidate.adapter_type,
        requires_browser=candidate.requires_browser,
        config={"metadata": candidate.metadata} if candidate.metadata else {},
    )

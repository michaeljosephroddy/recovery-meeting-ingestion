from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.normalize.canonical import CanonicalMeetingCandidate
from app.sources.registry import Source


class RawMeeting(BaseModel):
    source_id: str
    source_record_id: str
    source_url: str
    payload: dict[str, Any]
    content_hash: str
    fetched_at: str | None = None


class FetchResult(BaseModel):
    records: list[RawMeeting] = Field(default_factory=list)


class AdapterError(Exception):
    """Base exception for adapter failures."""


class AdapterFetchError(AdapterError):
    """Raised when a source cannot be fetched after retryable attempts."""


class AdapterPayloadError(AdapterError):
    """Raised when fetched source data is not shaped as expected."""


class SourceAdapter(Protocol):
    source: Source

    async def fetch(self) -> list[RawMeeting]:
        ...

    def normalize(self, raw: RawMeeting) -> CanonicalMeetingCandidate:
        ...

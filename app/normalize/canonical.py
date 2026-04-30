from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

Fellowship = Literal["aa", "ca", "na", "lifering", "smart"]
MeetingType = Literal["in_person", "online", "hybrid", "phone", "unknown"]
MeetingStatus = Literal["active", "stale", "inactive", "blocked"]


class MeetingOccurrence(BaseModel):
    day_of_week: int = Field(ge=0, le=6, description="0=Sunday, 6=Saturday")
    start_time_local: time
    end_time_local: time | None = None
    timezone: str

    @field_validator("timezone")
    @classmethod
    def timezone_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("timezone is required")
        return value


class CanonicalMeetingCandidate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    fellowship: Fellowship
    source_id: str
    source_record_id: str
    source_url: str
    name: str
    meeting_type: MeetingType = "unknown"
    venue_name: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_approximate_location: bool = False
    online_url: HttpUrl | None = None
    phone_join_info: str | None = None
    formats: list[str] = Field(default_factory=list)
    language: str | None = None
    accessibility_notes: str | None = None
    occurrences: list[MeetingOccurrence] = Field(default_factory=list)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_verified_at: datetime | None = None

    @field_validator("source_id", "source_record_id", "source_url", "name")
    @classmethod
    def required_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be blank")
        return value

    @model_validator(mode="after")
    def require_location_or_connection(self) -> "CanonicalMeetingCandidate":
        has_physical_location = any(
            value
            for value in (
                self.address_line1,
                self.city,
                self.venue_name,
                self.latitude,
                self.longitude,
            )
        )
        has_connection = bool(self.online_url or self.phone_join_info)
        if not has_physical_location and not has_connection:
            raise ValueError("meeting must have physical location data or online/phone details")
        return self


class CanonicalMeeting(CanonicalMeetingCandidate):
    id: str
    status: MeetingStatus = "active"
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)


class SnapshotMeeting(BaseModel):
    fellowship: Fellowship
    source_id: str
    source_record_id: str
    source_url: str
    name: str
    meeting_type: MeetingType
    venue_name: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    is_approximate_location: bool
    online_url: HttpUrl | None = None
    phone_join_info: str | None = None
    formats: list[str]
    language: str | None = None
    accessibility_notes: str | None = None
    occurrences: list[MeetingOccurrence]
    last_verified_at: datetime | None = None


class Snapshot(BaseModel):
    schema_version: str = "2026-04-30"
    generated_at: datetime
    service_date: date | None = None
    meetings: list[SnapshotMeeting]


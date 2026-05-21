from dataclasses import dataclass
from typing import Any, Literal, cast

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.adapters.base import RawMeeting
from app.normalize.canonical import CanonicalMeetingCandidate, Fellowship, MeetingOccurrence
from app.review.flags import ReviewFlag
from app.sources.registry import Source, normalize_source_url

ImportRunStatus = Literal["running", "succeeded", "failed"]


@dataclass(frozen=True)
class ImportRun:
    id: str
    source_id: str
    status: ImportRunStatus
    records_fetched: int
    records_changed: int
    review_flags_created: int
    error_message: str | None = None


class SourceRepository:
    def __init__(self, connection: Connection[Any]) -> None:
        self.connection = connection

    def upsert_source(self, source: Source) -> Source:
        normalized_url = source.normalized_url or normalize_source_url(source.url)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO sources (
                    id, fellowship, name, url, normalized_url, country, region, source_type,
                    adapter_type, permission_status, requires_browser, config, updated_at
                )
                VALUES (
                    %(id)s, %(fellowship)s, %(name)s, %(url)s, %(normalized_url)s, %(country)s,
                    %(region)s, %(source_type)s, %(adapter_type)s, %(permission_status)s,
                    %(requires_browser)s, %(config)s, NOW()
                )
                ON CONFLICT (normalized_url, fellowship)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    url = EXCLUDED.url,
                    country = COALESCE(EXCLUDED.country, sources.country),
                    region = COALESCE(EXCLUDED.region, sources.region),
                    source_type = EXCLUDED.source_type,
                    adapter_type = EXCLUDED.adapter_type,
                    permission_status = EXCLUDED.permission_status,
                    requires_browser = EXCLUDED.requires_browser,
                    config = sources.config || EXCLUDED.config,
                    updated_at = NOW()
                RETURNING
                    id, fellowship, name, url, normalized_url, country, region, source_type,
                    adapter_type, permission_status, requires_browser, config
                """,
                _source_params(source, normalized_url),
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("source upsert did not return a row")
        return _source_from_row(dict(row))

    def list_sources(self, fellowship: str | None = None) -> list[Source]:
        query = """
            SELECT
                id, fellowship, name, url, normalized_url, country, region, source_type,
                adapter_type, permission_status, requires_browser, config
            FROM sources
        """
        params: dict[str, object] = {}
        if fellowship is not None:
            query += " WHERE fellowship = %(fellowship)s"
            params["fellowship"] = fellowship
        query += " ORDER BY fellowship, country NULLS LAST, region NULLS LAST, name"
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, params)
            return [_source_from_row(dict(row)) for row in cursor.fetchall()]

    def count_sources(self) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM sources")
            row = cursor.fetchone()
        if row is None:
            return 0
        return int(row[0])

    def get_source(self, source_id: str) -> Source | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    id, fellowship, name, url, normalized_url, country, region, source_type,
                    adapter_type, permission_status, requires_browser, config
                FROM sources
                WHERE id = %(source_id)s
                """,
                {"source_id": source_id},
            )
            row = cursor.fetchone()
        return _source_from_row(dict(row)) if row is not None else None

    def delete_sources(self, source_ids: list[str]) -> int:
        if not source_ids:
            return 0
        with self.connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM sources WHERE id = ANY(%(source_ids)s)",
                {"source_ids": source_ids},
            )
            return cursor.rowcount or 0


class RawMeetingRepository:
    def __init__(self, connection: Connection[Any]) -> None:
        self.connection = connection

    def upsert_raw_meetings(self, records: list[RawMeeting]) -> int:
        inserted_or_existing = 0
        with self.connection.cursor() as cursor:
            for record in records:
                cursor.execute(
                    """
                    INSERT INTO raw_meetings (
                        source_id, source_record_id, source_url, content_hash, payload
                    )
                    VALUES (
                        %(source_id)s, %(source_record_id)s, %(source_url)s,
                        %(content_hash)s, %(payload)s
                    )
                    ON CONFLICT (source_id, source_record_id, content_hash) DO NOTHING
                    """,
                    {
                        "source_id": record.source_id,
                        "source_record_id": record.source_record_id,
                        "source_url": record.source_url,
                        "content_hash": record.content_hash,
                        "payload": Jsonb(record.payload),
                    },
                )
                inserted_or_existing += cursor.rowcount
        return inserted_or_existing


class CanonicalMeetingRepository:
    def __init__(self, connection: Connection[Any]) -> None:
        self.connection = connection

    def upsert_candidates(self, candidates: list[CanonicalMeetingCandidate]) -> int:
        changed = 0
        for candidate in candidates:
            meeting_id = self.upsert_candidate(candidate)
            self.replace_occurrences(meeting_id, candidate)
            changed += 1
        return changed

    def upsert_candidate(self, candidate: CanonicalMeetingCandidate) -> str:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO canonical_meetings (
                    fellowship, source_id, source_record_id, source_url, name, meeting_type,
                    venue_name, address_line1, address_line2, city, region, postal_code, country,
                    latitude, longitude, is_approximate_location, online_url, phone_join_info,
                    formats, language, accessibility_notes, last_seen_at, last_verified_at,
                    missing_run_count, updated_at
                )
                VALUES (
                    %(fellowship)s, %(source_id)s, %(source_record_id)s, %(source_url)s,
                    %(name)s, %(meeting_type)s, %(venue_name)s, %(address_line1)s,
                    %(address_line2)s, %(city)s, %(region)s, %(postal_code)s, %(country)s,
                    %(latitude)s, %(longitude)s, %(is_approximate_location)s, %(online_url)s,
                    %(phone_join_info)s, %(formats)s, %(language)s, %(accessibility_notes)s,
                    COALESCE(%(last_seen_at)s, NOW()), %(last_verified_at)s, 0, NOW()
                )
                ON CONFLICT (source_id, source_record_id)
                DO UPDATE SET
                    source_url = EXCLUDED.source_url,
                    name = EXCLUDED.name,
                    meeting_type = EXCLUDED.meeting_type,
                    venue_name = EXCLUDED.venue_name,
                    address_line1 = EXCLUDED.address_line1,
                    address_line2 = EXCLUDED.address_line2,
                    city = EXCLUDED.city,
                    region = EXCLUDED.region,
                    postal_code = EXCLUDED.postal_code,
                    country = EXCLUDED.country,
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    is_approximate_location = EXCLUDED.is_approximate_location,
                    online_url = EXCLUDED.online_url,
                    phone_join_info = EXCLUDED.phone_join_info,
                    formats = EXCLUDED.formats,
                    language = EXCLUDED.language,
                    accessibility_notes = EXCLUDED.accessibility_notes,
                    status = 'active',
                    missing_run_count = 0,
                    last_seen_at = EXCLUDED.last_seen_at,
                    last_verified_at = COALESCE(
                        EXCLUDED.last_verified_at,
                        canonical_meetings.last_verified_at
                    ),
                    updated_at = NOW()
                RETURNING id
                """,
                _candidate_params(candidate),
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("canonical meeting upsert did not return an id")
        return str(row[0])

    def count_active_for_source(self, source_id: str) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM canonical_meetings
                WHERE source_id = %(source_id)s
                  AND status = 'active'
                """,
                {"source_id": source_id},
            )
            row = cursor.fetchone()
        return int(row[0]) if row is not None else 0

    def mark_missing_for_source(self, source_id: str, seen_record_ids: set[str]) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE canonical_meetings
                SET missing_run_count = missing_run_count + 1,
                    status = CASE
                        WHEN missing_run_count + 1 >= 3 THEN 'inactive'
                        ELSE 'stale'
                    END,
                    updated_at = NOW()
                WHERE source_id = %(source_id)s
                  AND status IN ('active', 'stale')
                  AND NOT (source_record_id = ANY(%(seen_record_ids)s))
                """,
                {"source_id": source_id, "seen_record_ids": list(seen_record_ids)},
            )
            return cursor.rowcount

    def replace_occurrences(self, meeting_id: str, candidate: CanonicalMeetingCandidate) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM meeting_occurrences WHERE canonical_meeting_id = %(meeting_id)s",
                {"meeting_id": meeting_id},
            )
            for occurrence in candidate.occurrences:
                cursor.execute(
                    """
                    INSERT INTO meeting_occurrences (
                        canonical_meeting_id, day_of_week, start_time_local, end_time_local,
                        timezone
                    )
                    VALUES (
                        %(meeting_id)s, %(day_of_week)s, %(start_time_local)s,
                        %(end_time_local)s, %(timezone)s
                    )
                    """,
                    {
                        "meeting_id": meeting_id,
                        "day_of_week": occurrence.day_of_week,
                        "start_time_local": occurrence.start_time_local,
                        "end_time_local": occurrence.end_time_local,
                        "timezone": occurrence.timezone,
                    },
                )

    def count_meetings(self) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM canonical_meetings")
            row = cursor.fetchone()
        return int(row[0]) if row is not None else 0

    def count_occurrences(self) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM meeting_occurrences")
            row = cursor.fetchone()
        return int(row[0]) if row is not None else 0

    def list_active_candidates_for_snapshot(self) -> list[CanonicalMeetingCandidate]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    id, fellowship, source_id, source_record_id, source_url, name, meeting_type,
                    venue_name, address_line1, address_line2, city, region, postal_code, country,
                    latitude, longitude, is_approximate_location, online_url, phone_join_info,
                    formats, language, accessibility_notes, last_seen_at, last_verified_at
                FROM canonical_meetings
                WHERE status = 'active'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM review_flags rf
                      WHERE rf.source_id = canonical_meetings.source_id
                        AND rf.source_record_id = canonical_meetings.source_record_id
                        AND rf.status = 'open'
                        AND rf.severity = 'error'
                  )
                ORDER BY fellowship, country NULLS LAST, city NULLS LAST, name
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]
            occurrence_map = self._occurrences_for_meeting_ids([str(row["id"]) for row in rows])
        return [
            _candidate_from_row(row, occurrence_map.get(str(row["id"]), []))
            for row in rows
        ]

    def _occurrences_for_meeting_ids(
        self,
        meeting_ids: list[str],
    ) -> dict[str, list[MeetingOccurrence]]:
        if not meeting_ids:
            return {}
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    canonical_meeting_id, day_of_week, start_time_local, end_time_local, timezone
                FROM meeting_occurrences
                WHERE canonical_meeting_id = ANY(%(meeting_ids)s::uuid[])
                ORDER BY canonical_meeting_id, day_of_week, start_time_local
                """,
                {"meeting_ids": meeting_ids},
            )
            rows = cursor.fetchall()
        occurrence_map: dict[str, list[MeetingOccurrence]] = {}
        for row in rows:
            meeting_id = str(row["canonical_meeting_id"])
            occurrence_map.setdefault(meeting_id, []).append(
                MeetingOccurrence(
                    day_of_week=int(row["day_of_week"]),
                    start_time_local=row["start_time_local"],
                    end_time_local=row["end_time_local"],
                    timezone=str(row["timezone"]),
                )
            )
        return occurrence_map


class ReviewFlagRepository:
    def __init__(self, connection: Connection[Any]) -> None:
        self.connection = connection

    def replace_flags_for_source(self, source_id: str, flags: list[ReviewFlag]) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE review_flags
                SET status = 'resolved',
                    resolved_at = NOW()
                WHERE source_id = %(source_id)s
                  AND status = 'open'
                """,
                {"source_id": source_id},
            )
            inserted = 0
            for flag in flags:
                cursor.execute(
                    """
                    INSERT INTO review_flags (
                        source_id, source_record_id, code, severity, message
                    )
                    VALUES (
                        %(source_id)s, %(source_record_id)s, %(code)s, %(severity)s,
                        %(message)s
                    )
                    """,
                    {
                        "source_id": source_id,
                        "source_record_id": flag.source_record_id,
                        "code": flag.code,
                        "severity": flag.severity,
                        "message": flag.message,
                    },
                )
                inserted += cursor.rowcount
        return inserted

    def count_open_flags(self) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM review_flags WHERE status = 'open'")
            row = cursor.fetchone()
        return int(row[0]) if row is not None else 0

    def count_open_error_flags(self) -> int:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM review_flags WHERE status = 'open' AND severity = 'error'"
            )
            row = cursor.fetchone()
        return int(row[0]) if row is not None else 0


class SnapshotRepository:
    def __init__(self, connection: Connection[Any]) -> None:
        self.connection = connection

    def record_snapshot(
        self,
        *,
        schema_version: str,
        path: str,
        meeting_count: int,
        blocked_by_review_count: int,
        generated_at: object,
    ) -> str:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO snapshots (
                    schema_version, path, meeting_count, blocked_by_review_count, generated_at,
                    published_at
                )
                VALUES (
                    %(schema_version)s, %(path)s, %(meeting_count)s,
                    %(blocked_by_review_count)s, %(generated_at)s, NOW()
                )
                RETURNING id
                """,
                {
                    "schema_version": schema_version,
                    "path": path,
                    "meeting_count": meeting_count,
                    "blocked_by_review_count": blocked_by_review_count,
                    "generated_at": generated_at,
                },
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("snapshot insert did not return an id")
        return str(row[0])


class ImportRunRepository:
    def __init__(self, connection: Connection[Any]) -> None:
        self.connection = connection

    def start(self, source_id: str) -> ImportRun:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO import_runs (source_id, status)
                VALUES (%(source_id)s, 'running')
                RETURNING
                    id, source_id, status, records_fetched, records_changed,
                    review_flags_created, error_message
                """,
                {"source_id": source_id},
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError("import run insert did not return a row")
        return _import_run_from_row(dict(row))

    def finish(
        self,
        run_id: str,
        *,
        status: ImportRunStatus,
        records_fetched: int,
        records_changed: int,
        review_flags_created: int,
        error_message: str | None = None,
    ) -> ImportRun:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE import_runs
                SET status = %(status)s,
                    finished_at = NOW(),
                    records_fetched = %(records_fetched)s,
                    records_changed = %(records_changed)s,
                    review_flags_created = %(review_flags_created)s,
                    error_message = %(error_message)s
                WHERE id = %(run_id)s
                RETURNING
                    id, source_id, status, records_fetched, records_changed,
                    review_flags_created, error_message
                """,
                {
                    "run_id": run_id,
                    "status": status,
                    "records_fetched": records_fetched,
                    "records_changed": records_changed,
                    "review_flags_created": review_flags_created,
                    "error_message": error_message,
                },
            )
            row = cursor.fetchone()
        if row is None:
            raise RuntimeError(f"import run not found: {run_id}")
        return _import_run_from_row(dict(row))


def _source_params(source: Source, normalized_url: str) -> dict[str, object]:
    return {
        "id": source.id,
        "fellowship": source.fellowship,
        "name": source.name,
        "url": source.url,
        "normalized_url": normalized_url,
        "country": source.country,
        "region": source.region,
        "source_type": source.source_type.value,
        "adapter_type": source.adapter_type.value,
        "permission_status": source.permission_status,
        "requires_browser": source.requires_browser,
        "config": Jsonb(source.config),
    }


def _source_from_row(row: dict[str, Any]) -> Source:
    return Source(
        id=str(row["id"]),
        fellowship=cast(Fellowship, row["fellowship"]),
        name=str(row["name"]),
        url=str(row["url"]),
        normalized_url=str(row["normalized_url"]),
        country=row["country"],
        region=row["region"],
        source_type=row["source_type"],
        adapter_type=row["adapter_type"],
        permission_status=row["permission_status"],
        requires_browser=bool(row["requires_browser"]),
        config=row["config"] or {},
    )


def _candidate_params(candidate: CanonicalMeetingCandidate) -> dict[str, object]:
    return {
        "fellowship": candidate.fellowship,
        "source_id": candidate.source_id,
        "source_record_id": candidate.source_record_id,
        "source_url": candidate.source_url,
        "name": candidate.name,
        "meeting_type": candidate.meeting_type,
        "venue_name": candidate.venue_name,
        "address_line1": candidate.address_line1,
        "address_line2": candidate.address_line2,
        "city": candidate.city,
        "region": candidate.region,
        "postal_code": candidate.postal_code,
        "country": candidate.country,
        "latitude": candidate.latitude,
        "longitude": candidate.longitude,
        "is_approximate_location": candidate.is_approximate_location,
        "online_url": str(candidate.online_url) if candidate.online_url else None,
        "phone_join_info": candidate.phone_join_info,
        "formats": candidate.formats,
        "language": candidate.language,
        "accessibility_notes": candidate.accessibility_notes,
        "last_seen_at": candidate.last_seen_at,
        "last_verified_at": candidate.last_verified_at,
    }


def _candidate_from_row(
    row: dict[str, Any],
    occurrences: list[MeetingOccurrence],
) -> CanonicalMeetingCandidate:
    return CanonicalMeetingCandidate(
        fellowship=cast(Fellowship, row["fellowship"]),
        source_id=str(row["source_id"]),
        source_record_id=str(row["source_record_id"]),
        source_url=str(row["source_url"]),
        name=str(row["name"]),
        meeting_type=row["meeting_type"],
        venue_name=row["venue_name"],
        address_line1=row["address_line1"],
        address_line2=row["address_line2"],
        city=row["city"],
        region=row["region"],
        postal_code=row["postal_code"],
        country=row["country"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        is_approximate_location=bool(row["is_approximate_location"]),
        online_url=row["online_url"],
        phone_join_info=row["phone_join_info"],
        formats=list(row["formats"] or []),
        language=row["language"],
        accessibility_notes=row["accessibility_notes"],
        occurrences=occurrences,
        last_seen_at=row["last_seen_at"],
        last_verified_at=row["last_verified_at"],
    )


def _import_run_from_row(row: dict[str, Any]) -> ImportRun:
    return ImportRun(
        id=str(row["id"]),
        source_id=str(row["source_id"]),
        status=cast(ImportRunStatus, row["status"]),
        records_fetched=int(row["records_fetched"]),
        records_changed=int(row["records_changed"]),
        review_flags_created=int(row["review_flags_created"]),
        error_message=row["error_message"],
    )

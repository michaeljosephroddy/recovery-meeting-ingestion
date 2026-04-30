CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    fellowship TEXT NOT NULL CHECK (fellowship IN ('aa', 'ca', 'na', 'lifering', 'smart')),
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    country TEXT,
    region TEXT,
    source_type TEXT NOT NULL DEFAULT 'unknown',
    adapter_type TEXT NOT NULL DEFAULT 'unknown',
    permission_status TEXT NOT NULL DEFAULT 'unknown',
    requires_browser BOOLEAN NOT NULL DEFAULT FALSE,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_successful_run TIMESTAMPTZ,
    failure_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (normalized_url, fellowship)
);

CREATE TABLE IF NOT EXISTS import_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    records_fetched INT NOT NULL DEFAULT 0,
    records_changed INT NOT NULL DEFAULT 0,
    review_flags_created INT NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS raw_meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    source_record_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, source_record_id, content_hash)
);

CREATE TABLE IF NOT EXISTS canonical_meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fellowship TEXT NOT NULL CHECK (fellowship IN ('aa', 'ca', 'na', 'lifering', 'smart')),
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    source_record_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    name TEXT NOT NULL,
    meeting_type TEXT NOT NULL DEFAULT 'unknown',
    venue_name TEXT,
    address_line1 TEXT,
    address_line2 TEXT,
    city TEXT,
    region TEXT,
    postal_code TEXT,
    country TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    is_approximate_location BOOLEAN NOT NULL DEFAULT FALSE,
    online_url TEXT,
    phone_join_info TEXT,
    formats TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    language TEXT,
    accessibility_notes TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    missing_run_count INT NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_verified_at TIMESTAMPTZ,
    confidence_score DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, source_record_id)
);

CREATE TABLE IF NOT EXISTS meeting_occurrences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_meeting_id UUID NOT NULL REFERENCES canonical_meetings(id) ON DELETE CASCADE,
    day_of_week SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time_local TIME NOT NULL,
    end_time_local TIME,
    timezone TEXT NOT NULL,
    UNIQUE (canonical_meeting_id, day_of_week, start_time_local, timezone)
);

CREATE TABLE IF NOT EXISTS review_flags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id TEXT REFERENCES sources(id) ON DELETE CASCADE,
    canonical_meeting_id UUID REFERENCES canonical_meetings(id) ON DELETE CASCADE,
    source_record_id TEXT,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schema_version TEXT NOT NULL,
    path TEXT NOT NULL,
    meeting_count INT NOT NULL,
    blocked_by_review_count INT NOT NULL DEFAULT 0,
    generated_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ
);

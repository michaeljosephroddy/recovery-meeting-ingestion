# Add Structured Meeting Address Fields

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This plan follows `PLANS.md` in the repository root.

## Purpose / Big Picture

Meeting locations should be represented as structured address data instead of one ambiguous text blob. After this change, a snapshot row can carry a normalized street address, city, region or province, region code, postcode, country, and country code. This lets SoberSpace build filters using stable country and region identifiers while still displaying familiar names such as `Ontario, Canada` or `California, United States`.

The user-visible behavior is demonstrated by building a snapshot from examples like `810 E Princeton St, Ontario, CA 91764, USA` and observing that the exported meeting has `address_line1 = "810 E Princeton St"`, `city = "Ontario"`, `region = "California"`, `region_code = "CA"`, `postal_code = "91764"`, `country = "United States"`, and `country_code = "US"`. The same logic must preserve valid places such as `Greater London, Ontario, Canada` by using region and country context rather than assuming that "Greater London" always means the United Kingdom.

## Progress

- [x] (2026-05-26T12:37:04Z) Created this ExecPlan after inspecting `app/normalize/canonical.py`, `app/normalize/location_quality.py`, `app/export/snapshot.py`, and the current location-quality tests.
- [x] (2026-05-26T12:44:00Z) Added additive `region_code`, `country_code`, and `raw_location_text` fields to the Python canonical model, and additive `region_code` and `country_code` fields to snapshot meetings.
- [x] (2026-05-26T12:44:00Z) Extended the location normalizer to extract postcodes, country codes, region codes, and street-only address lines from common full-address strings.
- [x] (2026-05-26T12:44:00Z) Persisted the new canonical fields in the repository layer and added migration `003_structured_address_fields`.
- [x] (2026-05-26T12:44:00Z) Added focused tests for US, Canada, Australia, and UK address decomposition.
- [x] (2026-05-26T12:50:00Z) Exported `snapshots/meetings-2026-05-26T124444Z.json`, audited it, and dry-run validated it with the SoberSpace importer.
- [x] (2026-05-26T12:55:00Z) Removed `raw_location_text` from snapshot export to avoid adding debug/provenance payload to the public snapshot, then exported `snapshots/meetings-2026-05-26T125455Z.json`.
- [x] (2026-05-26T13:00:00Z) Ran focused and full validation: `tests/test_location_quality.py`, `tests/test_review_snapshot.py`, `tests/test_repositories_db.py`, `.venv/bin/pytest`, `git diff --check`, snapshot audit, and SoberSpace importer dry-run.

## Surprises & Discoveries

- Observation: The existing snapshot already has display-oriented fields named `address_line1`, `address_line2`, `city`, `region`, `postal_code`, and `country`, but no stable `region_code` or `country_code`.
    Evidence: `app/normalize/canonical.py` defines `SnapshotMeeting` with those display fields only.
- Observation: SoberSpace's current Go importer already has similarly named fields and should ignore additive JSON fields by default, but it will not store new fields until the backend importer and schema are extended.
    Evidence: `/home/michaelroddy/repos/project_radeon/internal/recoverymeetings/types.go` uses Go JSON decoding into a snapshot struct; unknown JSON fields are ignored by Go's standard decoder unless explicitly disallowed.
- Observation: Splitting ZIP/postcode into `postal_code` changed the shape of audit evidence. The audit initially reported 19 false country conflicts because US ZIPs were no longer in the same address segment as US state context.
    Evidence: The first audit of `snapshots/meetings-2026-05-26T124444Z.json` reported examples such as `Wood Ave & N Victoria Rd`, `region = Texas`, `postal_code = 78537` as Irish eircode evidence. Including the structured `region` field in the US state/ZIP evidence check restored the audit to only 6 known online timezone mismatches.

## Decision Log

- Decision: Keep `address_line1` as the normalized street-address field instead of introducing a separate `street_address` field in this pass.
    Rationale: The Python model, database, existing snapshots, and SoberSpace importer already use `address_line1`. Reusing it avoids a duplicate street field while still achieving structured address decomposition.
    Date/Author: 2026-05-26, Codex.
- Decision: Add `country_code` and `region_code` as additive fields and preserve full country/region names.
    Rationale: Names are good for display, but codes are better for frontend filters and API contracts. Keeping both supports stable filtering without losing readability.
    Date/Author: 2026-05-26, Codex.
- Decision: Keep the snapshot `schema_version` at `2026-04-30` for this ingestion-side pass.
    Rationale: The SoberSpace importer currently rejects unknown schema versions. The new JSON fields are additive and ignored by the current importer, which was verified by a dry-run. A future SoberSpace backend change should bump the schema version when it starts storing and serving the new fields.
    Date/Author: 2026-05-26, Codex.
- Decision: Do not export `raw_location_text` in the public snapshot.
    Rationale: The raw value is useful for ingestion debugging and future backfills, but it increased the snapshot by about 26 MB and does not help frontend filtering. The snapshot should carry the structured fields needed by consumers: street, city, region, region code, postcode, country, and country code.
    Date/Author: 2026-05-26, Codex.

## Outcomes & Retrospective

Implemented structured address standardization in the ingestion snapshot path. The new snapshot keeps the prior validated count profile while adding `country_code` and `region_code` fields for downstream consumers.

Final snapshot:

    path: snapshots/meetings-2026-05-26T125455Z.json
    active_meetings: 181627
    blocked_by_review: 172
    snapshot_id: ab067d4c-f01f-4e30-8477-13f34edd2da1
    sha256: 91e531a3b71cb200c0c4a0c4bcb667881cf1d687157c1a76fb652830e66d071f
    country_code populated: 173833
    region_code populated: 157251
    raw_location_text exported: false

Final audit:

    total_meetings: 181627
    issue_counts:
    - 6 timezone_country_mismatch

The remaining audit findings are the known NA online timezone rows from sources `na-9d00a0f0f235`, `na-6c5ffa036d86`, and `na-1f872a19071e`.

SoberSpace dry-run:

    Import run: b5b4bce7-ea44-4f12-9456-087ea21f90f5
    Meetings seen: 181627
    Meetings upserted: 181627
    Occurrences written: 176062
    Marked stale: 23519
    Marked inactive: 0

Validation:

    .venv/bin/pytest tests/test_location_quality.py
    .venv/bin/pytest tests/test_review_snapshot.py
    .venv/bin/pytest tests/test_repositories_db.py
    .venv/bin/pytest
    git diff --check

## Context and Orientation

The ingestion system turns scraped meeting records into `CanonicalMeetingCandidate` objects in `app/normalize/canonical.py`. `app/normalize/location_quality.py` performs source-aware country and region cleanup. `app/export/snapshot.py` builds the JSON snapshot consumed by SoberSpace. The repository layer in `app/storage/repositories.py` stores canonical meetings in the `canonical_meetings` table defined by `migrations/001_initial.sql` and Alembic migration files under `migrations/versions/`.

In this plan, "structured address fields" means one field for each major part of a physical address: street address (`address_line1` and optional `address_line2`), locality (`city`), administrative region (`region`), administrative region code (`region_code`), postcode (`postal_code`), country name (`country`), and country code (`country_code`). The term "region" covers US states, Canadian provinces and territories, Australian states and territories, and broad UK administrative regions where available.

## Plan of Work

First, add optional `country_code`, `region_code`, and `raw_location_text` fields to `CanonicalMeetingCandidate`, and optional `country_code` and `region_code` fields to `SnapshotMeeting`. `raw_location_text` preserves the original scraped location components in canonical storage for debugging, but it is not exported in snapshots because frontend consumers do not need it.

Second, extend `app/normalize/location_quality.py` so `normalize_candidate_location` can extract a postcode from the address line, strip trailing country text, split full address strings into a street-only `address_line1`, infer city from the segment before the region/postcode segment, and populate country/region codes. Existing source-aware disambiguation remains the authority for ambiguous cases like `Ontario, CA`, where `CA` can mean Canada or California depending on context.

Third, update `app/storage/repositories.py` and add an Alembic migration so canonical rows can persist the new fields. The migration must be additive and nullable so existing local databases remain valid after upgrading.

Fourth, add tests in `tests/test_location_quality.py` covering `Ontario, CA, USA`, `Greater London, Ontario, Canada`, Australian `NT` postcodes, and UK postcode evidence. The tests should show both human-readable fields and machine codes.

Finally, run the focused test file, run the full test suite, and verify `git diff --check`.

## Concrete Steps

Run all commands from `/home/michaelroddy/repos/recovery-meeting-ingestion`.

After editing the normalizer and models, run:

    .venv/bin/pytest tests/test_location_quality.py

After repository or migration edits, run:

    .venv/bin/pytest tests/test_repositories_db.py

Before finishing, run:

    .venv/bin/pytest
    git diff --check

## Validation and Acceptance

Acceptance is met when the new tests prove that full-address strings are decomposed into stable address parts and exported snapshots include both display names and codes. For `810 E Princeton St, Ontario, CA 91764, USA`, the exported meeting must identify Ontario as the city, California as the region, `CA` as the region code, `91764` as the postcode, and `US` as the country code. For `Greater London, Ontario, Canada`, the exported meeting must keep `Greater London` as the city/locality, `Ontario` as the region, `ON` as the region code, and `CA` as the country code.

## Idempotence and Recovery

The code changes are additive. The database migration only adds nullable columns and can be rerun through the project migration tooling. If a parsing rule proves too broad, revert that small rule and rerun `tests/test_location_quality.py`; no destructive data cleanup is part of this plan.

## Artifacts and Notes

No terminal validation output has been captured yet.

## Interfaces and Dependencies

The main interfaces at the end of this plan are:

- `CanonicalMeetingCandidate.country_code: str | None`
- `CanonicalMeetingCandidate.region_code: str | None`
- `CanonicalMeetingCandidate.raw_location_text: str | None`
- `SnapshotMeeting.country_code: str | None`
- `SnapshotMeeting.region_code: str | None`
- `normalize_candidate_location(candidate: CanonicalMeetingCandidate, source: Source | None = None) -> CanonicalMeetingCandidate`
- `country_code_for(country: str | None) -> str | None`
- `region_code_for(country: str | None, region: str | None) -> str | None`

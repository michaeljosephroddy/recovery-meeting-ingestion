import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.normalize.canonical import CanonicalMeetingCandidate, Snapshot, SnapshotMeeting
from app.normalize.dedupe import ConsolidationResult, consolidate_duplicate_candidates
from app.normalize.location_quality import normalize_candidate_location


@dataclass(frozen=True)
class SnapshotBuildResult:
    snapshot: Snapshot
    consolidation: ConsolidationResult


def build_snapshot(candidates: list[CanonicalMeetingCandidate]) -> Snapshot:
    return build_snapshot_with_quality(candidates).snapshot


def build_snapshot_with_quality(candidates: list[CanonicalMeetingCandidate]) -> SnapshotBuildResult:
    normalized_candidates = [normalize_candidate_location(candidate) for candidate in candidates]
    consolidation = consolidate_duplicate_candidates(normalized_candidates)
    snapshot = Snapshot(
        generated_at=datetime.now(UTC),
        meetings=[
            SnapshotMeeting(
                fellowship=candidate.fellowship,
                source_id=candidate.source_id,
                source_record_id=candidate.source_record_id,
                source_url=candidate.source_url,
                name=candidate.name,
                meeting_type=candidate.meeting_type,
                venue_name=candidate.venue_name,
                address_line1=candidate.address_line1,
                address_line2=candidate.address_line2,
                city=candidate.city,
                region=candidate.region,
                region_code=candidate.region_code,
                postal_code=candidate.postal_code,
                country=candidate.country,
                country_code=candidate.country_code,
                latitude=candidate.latitude,
                longitude=candidate.longitude,
                is_approximate_location=candidate.is_approximate_location,
                online_url=candidate.online_url,
                phone_join_info=candidate.phone_join_info,
                formats=candidate.formats,
                language=candidate.language,
                accessibility_notes=candidate.accessibility_notes,
                occurrences=candidate.occurrences,
                last_verified_at=candidate.last_verified_at,
            )
            for candidate in consolidation.candidates
        ],
    )
    return SnapshotBuildResult(snapshot=snapshot, consolidation=consolidation)


def write_snapshot(snapshot: Snapshot, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"meetings-{snapshot.generated_at.strftime('%Y-%m-%dT%H%M%SZ')}.json"
    path = output_dir / filename
    path.write_text(
        json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    shutil.copyfile(path, output_dir / "latest.json")
    return path

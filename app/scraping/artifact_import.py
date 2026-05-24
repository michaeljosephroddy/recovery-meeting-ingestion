import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from app.adapters.base import RawMeeting
from app.config import Settings
from app.ingest import IngestResult, ingest_raw_records
from app.sources.registry import (
    AdapterType,
    Source,
    SourceCandidate,
    SourceType,
    timezone_for_candidate,
)


@dataclass(frozen=True)
class ArtifactSourceImport:
    source: Source
    summary_path: Path
    scrape_status: str
    pages_visited: int
    records_extracted: int
    successful_pages: list[dict[str, object]]
    ingest: IngestResult
    error_message: str | None = None


def importable_artifact_summaries(
    artifact_dir: Path,
    *,
    source_id: str | None = None,
    include_failed: bool = False,
) -> list[Path]:
    summaries = sorted(artifact_dir.glob("*/summary.json"))
    if artifact_dir.name.endswith(".json") and artifact_dir.is_file():
        summaries = [artifact_dir]
    if source_id is not None:
        summaries = [path for path in summaries if path.parent.name == source_id]
    if include_failed:
        return summaries
    return [path for path in summaries if _summary_status(path) != "failed"]


def import_artifact_summary(
    summary_path: Path,
    settings: Settings,
    *,
    source_metadata: dict[str, Any] | None = None,
) -> ArtifactSourceImport:
    summary = _read_json_object(summary_path)
    source = _source_from_summary(summary, source_metadata)
    raw_records = _dedupe_raw_records(_raw_records_from_summary(source, summary))
    ingest = ingest_raw_records(source, settings, raw_records)
    return ArtifactSourceImport(
        source=source,
        summary_path=summary_path,
        scrape_status=str(summary.get("status") or "unknown"),
        pages_visited=_int(summary.get("pages_visited")),
        records_extracted=_int(summary.get("records_extracted")),
        successful_pages=_successful_pages_from_summary(summary),
        ingest=ingest,
        error_message=_optional_string(summary.get("error_message")),
    )


def _successful_pages_from_summary(summary: dict[str, Any]) -> list[dict[str, object]]:
    pages = summary.get("pages")
    if not isinstance(pages, list):
        return []
    successful_pages: list[dict[str, object]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        records = _int(page.get("extracted_count"))
        if records <= 0:
            continue
        url = _optional_string(page.get("final_url")) or _optional_string(page.get("url"))
        if not url:
            continue
        score_value = page.get("page_score")
        score = score_value if isinstance(score_value, int | float) else 0
        signals = page.get("page_signals")
        successful_pages.append(
            {
                "url": url,
                "records_extracted": records,
                "score": score,
                "signals": signals if isinstance(signals, list) else [],
            }
        )
    return successful_pages


def source_metadata_by_id(artifact_dir: Path) -> dict[str, dict[str, Any]]:
    report_path = artifact_dir / "controlled_smoke_report.json"
    if not report_path.exists():
        return {}
    report = _read_json_object(report_path)
    sources = report.get("sources")
    if not isinstance(sources, list):
        return {}
    metadata: dict[str, dict[str, Any]] = {}
    for item in sources:
        if not isinstance(item, dict):
            continue
        source_id = _optional_string(item.get("source_id"))
        if source_id:
            metadata[source_id] = item
    return metadata


def _raw_records_from_summary(source: Source, summary: dict[str, Any]) -> list[RawMeeting]:
    records: list[RawMeeting] = []
    pages = summary.get("pages")
    if not isinstance(pages, list):
        return records
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_url = _optional_string(page.get("final_url")) or _optional_string(page.get("url"))
        extracted = page.get("extracted")
        if not isinstance(extracted, list):
            continue
        for item in extracted:
            if not isinstance(item, dict):
                continue
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue
            payload = dict(payload)
            source_page_url = (
                _extraction_source_page_url(payload)
                or _optional_string(item.get("source_page_url"))
                or page_url
                or source.url
            )
            payload = _payload_with_extraction_metadata(payload, item, source_page_url)
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            records.append(
                RawMeeting(
                    source_id=source.id,
                    source_record_id=_source_record_id(payload),
                    source_url=source_page_url,
                    payload=payload,
                    content_hash=hashlib.sha256(encoded).hexdigest(),
                )
            )
    return records


def _payload_with_extraction_metadata(
    payload: dict[str, Any],
    item: dict[str, Any],
    source_page_url: str,
) -> dict[str, Any]:
    extraction = payload.get("extraction")
    extraction_metadata = dict(extraction) if isinstance(extraction, dict) else {}
    extraction_metadata.setdefault("method", item.get("method"))
    extraction_metadata.setdefault("confidence", item.get("confidence"))
    extraction_metadata.setdefault("source_page_url", source_page_url)
    item_signals = item.get("signals")
    extraction_metadata.setdefault(
        "signals",
        item_signals if isinstance(item_signals, list) else [],
    )
    extraction_metadata.setdefault("selector_hint", item.get("selector_hint"))
    payload["extraction"] = extraction_metadata
    return payload


def _source_from_summary(
    summary: dict[str, Any],
    metadata: dict[str, Any] | None,
) -> Source:
    source_id = _required_string(summary.get("source_id"), "source_id")
    source_url = _required_string(summary.get("source_url"), "source_url")
    fellowship = _optional_string((metadata or {}).get("fellowship")) or source_id.split("-", 1)[0]
    country = _optional_string((metadata or {}).get("country"))
    region = _optional_string((metadata or {}).get("region"))
    config: dict[str, Any] = {"scrape": {"artifact_import": True}}
    source_config = (metadata or {}).get("config")
    if isinstance(source_config, dict):
        config.update(source_config)
        scrape_value = config.get("scrape")
        scrape_config = dict(scrape_value) if isinstance(scrape_value, dict) else {}
        scrape_config["artifact_import"] = True
        config["scrape"] = scrape_config
    timezone = _optional_string((metadata or {}).get("timezone"))
    if timezone is None and source_config:
        timezone = _optional_string(config.get("timezone"))
    if timezone is None:
        timezone = timezone_for_candidate(
            SourceCandidate(
                fellowship=cast(Any, fellowship),
                label=_optional_string((metadata or {}).get("name")) or source_id,
                url=source_url,
                country=country,
                region=region,
            )
        )
    if timezone:
        config["timezone"] = timezone
    return Source(
        id=source_id,
        fellowship=cast(Any, fellowship),
        name=_optional_string((metadata or {}).get("name")) or source_id,
        url=source_url,
        country=country,
        region=region,
        source_type=SourceType.LOCAL_SERVICE_BODY,
        adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
        requires_browser=True,
        config=config,
    )


def _dedupe_raw_records(raw_records: list[RawMeeting]) -> list[RawMeeting]:
    deduped: list[RawMeeting] = []
    seen: set[str] = set()
    for record in raw_records:
        if record.source_record_id in seen:
            continue
        seen.add(record.source_record_id)
        deduped.append(record)
    return deduped


def _source_record_id(payload: dict[str, Any]) -> str:
    explicit = _optional_string(payload.get("source_record_id") or payload.get("id"))
    if explicit:
        return explicit
    basis = "|".join(
        _optional_string(payload.get(field)) or ""
        for field in (
            "name",
            "day",
            "time",
            "address_line1",
            "city",
            "online_url",
            "row_index",
        )
    )
    if not basis.strip("|"):
        basis = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(basis.encode(), usedforsecurity=False).hexdigest()[:16]


def _extraction_source_page_url(payload: dict[str, Any]) -> str | None:
    extraction = payload.get("extraction")
    if not isinstance(extraction, dict):
        return None
    return _optional_string(extraction.get("source_page_url"))


def _summary_status(path: Path) -> str:
    try:
        return str(_read_json_object(path).get("status") or "unknown")
    except ValueError:
        return "failed"


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _required_string(value: object, field: str) -> str:
    cleaned = _optional_string(value)
    if cleaned is None:
        raise ValueError(f"artifact summary is missing {field}")
    return cleaned


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0

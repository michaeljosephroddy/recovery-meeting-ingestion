import asyncio
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.sources.registry import Source


@dataclass(frozen=True)
class AuditPage:
    url: str
    final_url: str
    title: str | None
    score: float
    signals: list[str]
    extracted: int


@dataclass(frozen=True)
class ZeroSourceAuditEntry:
    id: str
    name: str
    url: str
    country: str | None
    region: str | None
    last_status: str | None
    last_records: int | None
    artifact_dir: str | None
    bucket: str
    priority: int
    signals: list[str]
    error: str
    pages: list[AuditPage] = field(default_factory=list)
    text_sample: str = ""


@dataclass(frozen=True)
class ZeroSourceAuditResult:
    entries: list[ZeroSourceAuditEntry]
    retry_source_ids: list[str]

    @property
    def bucket_counts(self) -> Counter[str]:
        return Counter(entry.bucket for entry in self.entries)

    @property
    def priority_counts(self) -> Counter[int]:
        return Counter(entry.priority for entry in self.entries)

    @property
    def country_counts(self) -> Counter[str]:
        return Counter(entry.country or "Unknown" for entry in self.entries)


_DAY_TIME_RE = re.compile(
    r"(?is)\b("
    r"mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|"
    r"sat(?:urday)?|sun(?:day)?|lunes|martes|miercoles|miércoles|jueves|"
    r"viernes|sabado|sábado|domingo|понедельник|вторник|среда|четверг|"
    r"пятница|суббота|воскресенье|monday|화요일|수요일|목요일|금요일|토요일|"
    r"일요일|월요일|月曜|火曜|水曜|木曜|金曜|土曜|日曜"
    r")\b.{0,180}\b\d{1,2}\s*(?::|\.|h|時)\s*\d{2}",
)
_TIME_RANGE_RE = re.compile(
    r"(?is)\b\d{1,2}\s*(?::|\.|h|時)\s*\d{2}\s*(?:am|pm)?\s*(?:-|to|–|—|~|〜|～)"
)
_MEETING_KEYWORD_RE = re.compile(
    r"(?is)\b("
    r"meeting|meetings|schedule|group|groups|narcotics anonymous|"
    r"reunion|reuniones|grupo|grupos|расписание|групп|зустріч|"
    r"모임|일정|ミーティング|会場|会議|集会"
    r")\b"
)
_FORM_RE = re.compile(r"(?is)<form\b|<select\b|type=[\"']?search\b")
_TABLE_RE = re.compile(r"(?is)<table\b|class=[\"'][^\"']*(meeting|schedule|bmlt|crouton)")
_BLOCKED_RE = re.compile(
    r"(?is)\b("
    r"captcha|cloudflare|access denied|forbidden|blocked|security check|"
    r"verify you are human|enable javascript and cookies"
    r")\b"
)
_DEAD_RE = re.compile(
    r"(?is)\b("
    r"404|not found|server error|internal server error|critical error|"
    r"domain for sale|account suspended|site suspended|website expired|"
    r"page cannot be found|temporarily unavailable"
    r")\b"
)
_TRANSPORT_RE = re.compile(r"(?is)(name_not_resolved|dns|connect|connection|protocol|transport)")
_TIMEOUT_RE = re.compile(r"(?is)(timeout|timed out)")
_TLS_RE = re.compile(r"(?is)(ssl|tls|certificate|cert_|common name)")

_STRUCTURED_FEED_RE = re.compile(
    r"(?is)("
    r"client_interface/(?:json|php)|main_server|root_server|bmltenabled|"
    r"crouton|meetingguide|meeting-guide|/feed/json|wp-json/[^\"']*meeting|"
    r"service_body|services\[\]"
    r")"
)
_PDF_RE = re.compile(
    r"(?is)("
    r"current-meeting-list|(?:meeting|meetings|schedule|where(?:-|\s*)and(?:-|\s*)when|"
    r"printable|list)[^\"'<>]{0,180}\.pdf|\.pdf[^\"'<>]{0,180}"
    r"(?:meeting|meetings|schedule|where(?:-|\s*)and(?:-|\s*)when|printable|list)"
    r")"
)
_EMBED_URL_HINT_RE = re.compile(
    r"(?is)(calendar\.google|/calendar/|basic\.ics|bmlt|crouton|meeting|meetings|"
    r"schedule|picker|airtable|jotform|tockify|teamup|timekit)"
)


def latest_artifact_dirs_by_source(artifact_root: Path) -> dict[str, Path]:
    summaries = list(artifact_root.glob("*/summary.json"))
    summaries.extend(artifact_root.glob("*/*/summary.json"))
    by_source: dict[str, tuple[float, Path]] = {}
    for summary_path in summaries:
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source_id = payload.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            continue
        artifact_dir = summary_path.parent
        try:
            modified = summary_path.stat().st_mtime
        except OSError:
            modified = 0.0
        if source_id not in by_source or modified > by_source[source_id][0]:
            by_source[source_id] = (modified, artifact_dir)
    return {source_id: artifact_dir for source_id, (_, artifact_dir) in by_source.items()}


async def audit_zero_sources(
    sources: list[Source],
    *,
    artifact_root: Path,
    concurrency: int = 16,
    live_probe: bool = True,
    max_pages: int = 8,
) -> ZeroSourceAuditResult:
    artifact_dirs = latest_artifact_dirs_by_source(artifact_root)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(12.0),
        headers={"User-Agent": "SoberSpaceRecoveryMeetingIngestion/0.1 zero-source-audit"},
    ) as client:

        async def inspect(source: Source) -> ZeroSourceAuditEntry:
            async with semaphore:
                return await _inspect_source(
                    source,
                    artifact_dirs.get(source.id),
                    max_pages,
                    client if live_probe else None,
                )

        entries = await asyncio.gather(*(inspect(source) for source in sources))

    sorted_entries = sorted(
        entries,
        key=lambda entry: (entry.priority, entry.bucket, entry.country or "", entry.name),
    )
    retry_ids = [
        entry.id
        for entry in sorted_entries
        if entry.priority <= 2
        and entry.bucket
        in {
            "parser_gap_candidate",
            "possible_missed_structured_feed",
            "possible_pdf_or_printable",
            "possible_embed_or_calendar",
        }
    ]
    return ZeroSourceAuditResult(entries=sorted_entries, retry_source_ids=retry_ids)


def write_zero_source_audit(
    result: ZeroSourceAuditResult,
    output_dir: Path,
    *,
    fellowship: str,
    retry_command: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "audit.json").write_text(
        json.dumps([_entry_to_json(entry) for entry in result.entries], indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "retry-source-ids.txt").write_text(
        "\n".join(result.retry_source_ids) + ("\n" if result.retry_source_ids else ""),
        encoding="utf-8",
    )
    (output_dir / "retry-command.txt").write_text(retry_command + "\n", encoding="utf-8")
    (output_dir / "audit.md").write_text(
        _render_markdown(result, fellowship=fellowship, retry_command=retry_command),
        encoding="utf-8",
    )


def classify_zero_source_text(
    *,
    html: str,
    text: str,
    last_status: str | None = "succeeded",
    error: str = "",
) -> tuple[str, int, list[str]]:
    haystack = f"{html}\n{text}\n{error}".lower()
    signals: set[str] = set()

    if _BLOCKED_RE.search(haystack):
        signals.add("blocked")
    if _DEAD_RE.search(haystack):
        signals.add("dead_error")
    if _FORM_RE.search(html):
        signals.add("form")
    if _TABLE_RE.search(html):
        signals.add("table")
    if _MEETING_KEYWORD_RE.search(text):
        signals.add("meeting_keyword")
    if _DAY_TIME_RE.search(text) or (_TIME_RANGE_RE.search(text) and "meeting_keyword" in signals):
        signals.add("day_time_or_meeting_time")
    if _STRUCTURED_FEED_RE.search(haystack):
        signals.add("structured_feed")
    if _PDF_RE.search(haystack):
        signals.add("pdf")
    if _has_real_embed(html):
        signals.add("embed")

    status = (last_status or "").lower()
    if status == "failed":
        bucket, priority = _failed_bucket(error or haystack)
    elif "structured_feed" in signals:
        bucket, priority = "possible_missed_structured_feed", 1
    elif "pdf" in signals:
        bucket, priority = "possible_pdf_or_printable", 1
    elif "embed" in signals:
        priority = 1 if "day_time_or_meeting_time" in signals else 2
        bucket = "possible_embed_or_calendar"
    elif "day_time_or_meeting_time" in signals and "dead_error" not in signals:
        bucket, priority = "parser_gap_candidate", 1
    elif "blocked" in signals:
        bucket, priority = "blocked_or_captcha", 5
    elif "dead_error" in signals:
        bucket, priority = "dead_or_error_page", 5
    elif "meeting_keyword" in signals:
        bucket, priority = "meeting_keywords_only", 4
    else:
        bucket, priority = "low_signal", 5

    return bucket, priority, sorted(signals)


async def _inspect_source(
    source: Source,
    indexed_artifact_dir: Path | None,
    max_pages: int,
    client: httpx.AsyncClient | None,
) -> ZeroSourceAuditEntry:
    scrape_config = source.config.get("scrape")
    scrape_config = scrape_config if isinstance(scrape_config, dict) else {}
    configured_artifact = scrape_config.get("last_artifact_dir")
    artifact_dir = (
        Path(configured_artifact)
        if isinstance(configured_artifact, str)
        else indexed_artifact_dir
    )
    if artifact_dir is not None and not artifact_dir.exists():
        artifact_dir = indexed_artifact_dir

    pages, html, text, summary_error = _artifact_evidence(artifact_dir, max_pages)
    last_status = _string_or_none(scrape_config.get("last_status"))
    last_records = _int_or_none(scrape_config.get("last_records_extracted"))
    error = _string_or_none(scrape_config.get("last_error")) or summary_error or ""

    if client is not None and (not text or last_status == "failed"):
        probe_html, probe_text, probe_error = await _probe_source(client, source.url)
        if probe_html or probe_text:
            html = f"{html}\n{probe_html}"
            text = f"{text}\n{probe_text}"
        if probe_error and not error:
            error = probe_error

    bucket, priority, signals = classify_zero_source_text(
        html=html,
        text=text,
        last_status=last_status,
        error=error,
    )
    return ZeroSourceAuditEntry(
        id=source.id,
        name=source.name,
        url=source.url,
        country=source.country,
        region=source.region,
        last_status=last_status,
        last_records=last_records,
        artifact_dir=str(artifact_dir) if artifact_dir is not None else None,
        bucket=bucket,
        priority=priority,
        signals=signals,
        error=error,
        pages=pages,
        text_sample=_compact_text(text)[:700],
    )


def _artifact_evidence(
    artifact_dir: Path | None,
    max_pages: int,
) -> tuple[list[AuditPage], str, str, str]:
    if artifact_dir is None:
        return [], "", "", ""
    summary_path = artifact_dir / "summary.json"
    summary_error = ""
    pages: list[AuditPage] = []
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            summary = {}
        if isinstance(summary, dict):
            summary_error = str(summary.get("error_message") or "")
            for page in summary.get("pages") or []:
                if not isinstance(page, dict):
                    continue
                pages.append(
                    AuditPage(
                        url=str(page.get("url") or ""),
                        final_url=str(page.get("final_url") or ""),
                        title=_string_or_none(page.get("title")),
                        score=float(page.get("page_score") or 0.0),
                        signals=[
                            str(signal)
                            for signal in page.get("page_signals") or []
                            if isinstance(signal, str)
                        ],
                        extracted=_int_or_none(page.get("extracted_count")) or 0,
                    )
                )
    html_parts: list[str] = []
    text_parts: list[str] = []
    pages_dir = artifact_dir / "pages"
    for html_path in sorted(pages_dir.glob("*.html"))[:max_pages]:
        try:
            page_html = html_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        html_parts.append(page_html[:250_000])
        text_parts.append(_html_to_text(page_html))
    return pages, "\n".join(html_parts), "\n".join(text_parts), summary_error


async def _probe_source(client: httpx.AsyncClient, url: str) -> tuple[str, str, str]:
    try:
        response = await client.get(url)
        html = response.text[:250_000]
        error = "" if response.status_code < 400 else f"HTTP {response.status_code}"
        return html, _html_to_text(html), error
    except Exception as exc:
        return "", "", str(exc)


def _failed_bucket(error: str) -> tuple[str, int]:
    if _TIMEOUT_RE.search(error):
        return "failed_timeout", 4
    if _TLS_RE.search(error):
        return "failed_tls_ssl", 4
    if _TRANSPORT_RE.search(error):
        return "failed_transport", 4
    return "failed_transport", 4


def _has_real_embed(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["iframe", "embed", "object"]):
        src = tag.get("src") or tag.get("data")
        if not src:
            continue
        nearby = " ".join(
            [
                str(src),
                tag.get_text(" ", strip=True),
                str(tag.parent.get_text(" ", strip=True) if tag.parent else ""),
            ]
        )
        if _EMBED_URL_HINT_RE.search(nearby):
            return True
    return False


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return _compact_text(soup.get_text(" ", strip=True))


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _entry_to_json(entry: ZeroSourceAuditEntry) -> dict[str, Any]:
    payload = asdict(entry)
    payload["pages"] = [asdict(page) for page in entry.pages]
    return payload


def _render_markdown(
    result: ZeroSourceAuditResult,
    *,
    fellowship: str,
    retry_command: str,
) -> str:
    lines = [
        f"# {fellowship.upper()} zero-active source audit",
        "",
        f"Total zero-active browser sources: {len(result.entries)}",
        f"Curated retry source IDs: {len(result.retry_source_ids)}",
        "",
        "## Buckets",
    ]
    lines.extend(f"- {bucket}: {count}" for bucket, count in result.bucket_counts.most_common())
    lines.extend(["", "## Priority counts"])
    lines.extend(
        f"- P{priority}: {count}"
        for priority, count in sorted(result.priority_counts.items())
    )
    lines.extend(["", "## Top countries"])
    lines.extend(
        f"- {country}: {count}" for country, count in result.country_counts.most_common(20)
    )
    lines.extend(["", "## Retry command", "", "```bash", retry_command, "```"])
    lines.extend(["", "## Recommended next curated retry candidates"])
    for entry in result.entries:
        if entry.id not in result.retry_source_ids:
            continue
        region = f" / {entry.region}" if entry.region else ""
        lines.append(
            f"- P{entry.priority} {entry.bucket} `{entry.id}` "
            f"{entry.country or 'Unknown'}{region}: {entry.name} - {entry.url} "
            f"signals={','.join(entry.signals) or 'none'}"
        )
    lines.extend(["", "## Likely defer/manual"])
    for entry in result.entries:
        if entry.id in result.retry_source_ids or entry.priority < 4:
            continue
        region = f" / {entry.region}" if entry.region else ""
        lines.append(
            f"- P{entry.priority} {entry.bucket} `{entry.id}` "
            f"{entry.country or 'Unknown'}{region}: {entry.name} - {entry.url} "
            f"signals={','.join(entry.signals) or 'none'}"
        )
    return "\n".join(lines) + "\n"

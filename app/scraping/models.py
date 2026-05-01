from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CrawlSettings:
    max_pages_per_source: int = 20
    max_depth: int = 2
    page_timeout_ms: int = 20_000
    action_timeout_ms: int = 5_000
    max_actions_per_page: int = 20
    save_artifacts: bool = True
    headless: bool = True


@dataclass(frozen=True)
class BrowserActionTrace:
    action: str
    selector: str | None = None
    value: str | None = None
    status: str = "succeeded"
    message: str | None = None


@dataclass(frozen=True)
class ExtractedMeeting:
    payload: dict[str, Any]
    method: str
    confidence: float
    source_page_url: str
    signals: list[str] = field(default_factory=list)
    selector_hint: str | None = None

    def payload_with_metadata(self) -> dict[str, Any]:
        payload = dict(self.payload)
        payload["extraction"] = {
            "method": self.method,
            "confidence": self.confidence,
            "source_page_url": self.source_page_url,
            "signals": self.signals,
            "selector_hint": self.selector_hint,
        }
        return payload


@dataclass(frozen=True)
class ScrapedPage:
    url: str
    final_url: str
    title: str | None
    html: str
    page_score: float = 0.0
    page_signals: list[str] = field(default_factory=list)
    actions: list[BrowserActionTrace] = field(default_factory=list)
    extracted: list[ExtractedMeeting] = field(default_factory=list)
    screenshot_path: str | None = None
    evidence_path: str | None = None

    @property
    def extracted_count(self) -> int:
        return len(self.extracted)


@dataclass(frozen=True)
class ScrapeSourceResult:
    source_id: str
    source_url: str
    status: str
    pages: list[ScrapedPage] = field(default_factory=list)
    error_message: str | None = None
    artifact_dir: str | None = None

    @property
    def pages_visited(self) -> int:
        return len(self.pages)

    @property
    def records_extracted(self) -> int:
        return sum(page.extracted_count for page in self.pages)

    def to_summary(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "status": self.status,
            "pages_visited": self.pages_visited,
            "records_extracted": self.records_extracted,
            "error_message": self.error_message,
            "artifact_dir": self.artifact_dir,
            "pages": [
                {
                    **_without_html(page),
                    "actions": [asdict(action) for action in page.actions],
                    "extracted": [
                        {
                            "payload": meeting.payload_with_metadata(),
                            "method": meeting.method,
                            "confidence": meeting.confidence,
                            "source_page_url": meeting.source_page_url,
                            "signals": meeting.signals,
                            "selector_hint": meeting.selector_hint,
                        }
                        for meeting in page.extracted
                    ],
                }
                for page in self.pages
            ],
        }


def _without_html(page: ScrapedPage) -> dict[str, Any]:
    return {
        "url": page.url,
        "final_url": page.final_url,
        "title": page.title,
        "page_score": page.page_score,
        "page_signals": page.page_signals,
        "extracted_count": page.extracted_count,
        "screenshot_path": page.screenshot_path,
        "evidence_path": page.evidence_path,
    }


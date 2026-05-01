import json
from dataclasses import asdict
from hashlib import sha1
from pathlib import Path
from typing import Any

from app.scraping.models import ScrapeSourceResult


def write_scrape_evidence(result: ScrapeSourceResult, output_dir: Path) -> Path:
    run_dir = output_dir / result.source_id
    run_dir.mkdir(parents=True, exist_ok=True)

    pages_dir = run_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    for index, page in enumerate(result.pages, start=1):
        page_id = _page_id(index, page.final_url)
        (pages_dir / f"{page_id}.html").write_text(page.html, encoding="utf-8")
        _write_json(
            pages_dir / f"{page_id}.json",
            {
                "url": page.url,
                "final_url": page.final_url,
                "title": page.title,
                "page_score": page.page_score,
                "page_signals": page.page_signals,
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
            },
        )

    _write_json(run_dir / "summary.json", result.to_summary())
    return run_dir


def read_scrape_summary(path: Path) -> dict[str, Any]:
    payload = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("scrape summary must be a JSON object")
    return payload


def _page_id(index: int, url: str) -> str:
    digest = sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"{index:03d}-{digest}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


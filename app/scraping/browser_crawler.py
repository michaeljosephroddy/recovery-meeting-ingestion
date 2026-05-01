from collections import deque
from contextlib import suppress
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

from app.adapters.base import AdapterPayloadError
from app.scraping.evidence import write_scrape_evidence
from app.scraping.extract_meetings import extract_meetings_from_html
from app.scraping.interactions import (
    browser_config_from_source,
    configured_actions_from_source,
    perform_configured_actions,
    perform_heuristic_interactions,
)
from app.scraping.meeting_page_detector import score_html, score_link
from app.scraping.models import CrawlSettings, ScrapedPage, ScrapeSourceResult
from app.sources.registry import Source

SKIP_PATH_SUFFIXES = (
    ".avi",
    ".doc",
    ".docx",
    ".gif",
    ".jpg",
    ".jpeg",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
)


class BrowserCrawler:
    def __init__(
        self,
        source: Source,
        *,
        user_agent: str,
        settings: CrawlSettings | None = None,
        artifact_dir: Path | None = None,
    ) -> None:
        self.source = source
        self.user_agent = user_agent
        self.settings = settings or CrawlSettings()
        self.artifact_dir = artifact_dir

    async def crawl(self) -> ScrapeSourceResult:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise AdapterPayloadError(
                "playwright optional dependency is required for browser crawling"
            ) from exc

        pages: list[ScrapedPage] = []
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=self.settings.headless)
                context = await browser.new_context(user_agent=self.user_agent)
                page = await context.new_page()
                page.set_default_timeout(self.settings.page_timeout_ms)
                queue: deque[tuple[str, int]] = deque([(self.source.url, 0)])
                visited: set[str] = set()
                visited_final: set[str] = set()
                while queue and len(pages) < self.settings.max_pages_per_source:
                    url, depth = queue.popleft()
                    normalized = normalize_crawl_url(url)
                    if (
                        normalized in visited
                        or normalized in visited_final
                        or not is_allowed_url(self.source.url, normalized)
                    ):
                        continue
                    visited.add(normalized)
                    scraped = await self._scrape_page(page, normalized)
                    final_normalized = normalize_crawl_url(scraped.final_url)
                    if final_normalized in visited_final:
                        continue
                    visited_final.add(final_normalized)
                    pages.append(scraped)
                    if depth >= self.settings.max_depth:
                        continue
                    links = await _page_links(page, scraped.final_url)
                    for link in prioritize_links(self.source.url, links):
                        link_url = normalize_crawl_url(link["url"])
                        if link_url not in visited:
                            queue.append((link_url, depth + 1))
                await browser.close()
        except Exception as exc:
            result = ScrapeSourceResult(
                source_id=self.source.id,
                source_url=self.source.url,
                status="failed",
                pages=pages,
                error_message=str(exc),
            )
            return self._write_evidence_if_requested(result)

        result = ScrapeSourceResult(
            source_id=self.source.id,
            source_url=self.source.url,
            status="succeeded",
            pages=pages,
        )
        return self._write_evidence_if_requested(result)

    async def _scrape_page(self, page: Any, url: str) -> ScrapedPage:
        browser_config = browser_config_from_source(self.source)
        wait_until = str(browser_config.get("wait_until") or "networkidle")
        try:
            await page.goto(url, wait_until=wait_until, timeout=self.settings.page_timeout_ms)
        except Exception as exc:
            if wait_until != "networkidle" or "Timeout" not in str(exc):
                raise
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.settings.page_timeout_ms,
            )
        traces = await perform_configured_actions(page, configured_actions_from_source(self.source))
        traces.extend(await perform_heuristic_interactions(page, self.source, self.settings))
        wait_for_selector = browser_config.get("wait_for_selector")
        if wait_for_selector:
            await page.wait_for_selector(str(wait_for_selector))
        with suppress(Exception):
            await page.wait_for_load_state("domcontentloaded", timeout=2_000)
        html = await _safe_page_content(page)
        final_url = str(page.url)
        title = await page.title()
        page_score = score_html(final_url, html)
        extracted = extract_meetings_from_html(
            html,
            source_page_url=final_url,
            source_config=self.source.config,
        )
        screenshot_path = None
        if self.artifact_dir is not None and self.settings.save_artifacts:
            screenshots = self.artifact_dir / self.source.id / "screenshots"
            screenshots.mkdir(parents=True, exist_ok=True)
            screenshot_id = sha1(final_url.encode(), usedforsecurity=False).hexdigest()[:10]
            screenshot_path = str(screenshots / f"{screenshot_id}.png")
            try:
                await page.screenshot(path=screenshot_path, full_page=True)
            except Exception:
                screenshot_path = None
        return ScrapedPage(
            url=url,
            final_url=final_url,
            title=title,
            html=html,
            page_score=page_score.score,
            page_signals=page_score.signals,
            actions=traces,
            extracted=extracted,
            screenshot_path=screenshot_path,
        )

    def _write_evidence_if_requested(self, result: ScrapeSourceResult) -> ScrapeSourceResult:
        if self.artifact_dir is None or not self.settings.save_artifacts:
            return result
        evidence_dir = write_scrape_evidence(result, self.artifact_dir)
        return ScrapeSourceResult(
            source_id=result.source_id,
            source_url=result.source_url,
            status=result.status,
            pages=result.pages,
            error_message=result.error_message,
            artifact_dir=str(evidence_dir),
        )


def normalize_crawl_url(url: str) -> str:
    return urldefrag(url.strip())[0]


def is_allowed_url(source_url: str, candidate_url: str) -> bool:
    source_host = urlparse(source_url).hostname or ""
    candidate = urlparse(candidate_url)
    if candidate.scheme not in {"http", "https"}:
        return False
    if candidate.path.lower().endswith(SKIP_PATH_SUFFIXES):
        return False
    candidate_host = candidate.hostname or ""
    if candidate_host == source_host:
        return True
    source_root = ".".join(source_host.split(".")[-2:])
    candidate_root = ".".join(candidate_host.split(".")[-2:])
    return bool(source_root and source_root == candidate_root)


def prioritize_links(source_url: str, links: list[dict[str, str]]) -> list[dict[str, str]]:
    allowed = [link for link in links if is_allowed_url(source_url, link["url"])]
    return sorted(
        allowed,
        key=lambda link: score_link(link["url"], link.get("text", "")).score,
        reverse=True,
    )


async def _page_links(page: Any, base_url: str) -> list[dict[str, str]]:
    raw_links = await page.eval_on_selector_all(
        "a[href]",
        """
        links => links.map(link => ({
          url: link.getAttribute('href'),
          text: link.textContent || ''
        }))
        """,
    )
    links: list[dict[str, str]] = []
    if not isinstance(raw_links, list):
        return links
    for raw_link in raw_links:
        if not isinstance(raw_link, dict):
            continue
        href = raw_link.get("url")
        if not href:
            continue
        links.append(
            {
                "url": normalize_crawl_url(urljoin(base_url, str(href))),
                "text": str(raw_link.get("text") or ""),
            }
        )
    return links


async def _safe_page_content(page: Any) -> str:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            return str(await page.content())
        except Exception as exc:
            last_error = exc
            with suppress(Exception):
                await page.wait_for_load_state("domcontentloaded", timeout=2_000)
            await page.wait_for_timeout(500)
    if last_error is not None:
        raise last_error
    return str(await page.content())

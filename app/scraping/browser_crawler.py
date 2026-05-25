import asyncio
import base64
import json
import re
from collections import deque
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha1
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urldefrag, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.adapters.base import AdapterPayloadError
from app.adapters.pdf import extract_pdf_text
from app.scraping.evidence import write_scrape_evidence
from app.scraping.extract_meetings import extract_meetings_from_html
from app.scraping.interactions import (
    browser_config_from_source,
    configured_actions_from_source,
    perform_configured_actions,
    perform_heuristic_interactions,
)
from app.scraping.meeting_page_detector import PageScore, score_html, score_link
from app.scraping.models import (
    BrowserActionTrace,
    CrawlSettings,
    ExtractedMeeting,
    ScrapedPage,
    ScrapeSourceResult,
)
from app.scraping.scoring import confidence_for_payload
from app.sources.registry import Source, SourceType

SKIP_PATH_SUFFIXES = (
    ".avi",
    ".doc",
    ".docx",
    ".gif",
    ".ics",
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
SKIP_PATH_MARKERS = (
    "/feed/bmlt2ics",
)
SKIP_QUERY_KEYS = {
    "current-meeting-list",
}
COMMON_MEETING_PATHS = (
    "/meeting/",
    "/meeting",
    "/meetings/",
    "/meetings",
    "/meetings/find-a-meeting",
    "/meetings/find-a-meeting/",
    "/groups/",
    "/groups",
    "/aa-groups/",
    "/aa-groups",
    "/a-a-groups/",
    "/a-a-groups",
    "/alcoholics-anonymous-groups/",
    "/alcoholics-anonymous-groups",
    "/meeting-schedule",
    "/meeting-schedule/",
    "/meetings-schedule",
    "/meetings-schedule/",
    "/meeting-list",
    "/meeting-list/",
    "/meeting-list.html",
    "/meeting-locator",
    "/meeting-locator/",
    "/meeting-locations",
    "/meeting-locations/",
    "/meeting-schedule",
    "/meeting-schedule/",
    "/meetings-map",
    "/meetings-map/",
    "/locations",
    "/locations/",
    "/area-meetings",
    "/area-meetings/",
    "/local-meeting-schedule",
    "/local-meeting-schedule/",
    "/na-meetings",
    "/na-meetings/",
    "/na-meetings.html",
    "/tabbed-map-search",
    "/tabbed-map-search/",
    "/tabbed-search",
    "/tabbed-search/",
    "/where-and-when",
    "/where-and-when/",
    "/where-and-when.html",
    "/bmlt-meeting-list",
    "/bmlt-meeting-list/",
    "/bmlt-tabbed-search",
    "/bmlt-tabbed-search/",
    "/find-a-meeting",
    "/find-a-meeting/",
    "/find-meeting/find-a-meeting",
    "/find-meeting/find-a-meeting/",
    "/find-meeting",
    "/find-meeting/",
    "/find-meetings",
    "/find-meetings/",
    "/meeting-search",
    "/meeting-search/",
    "/meetings-search",
    "/meetings-search/",
    "/search-meetings",
    "/search-meetings/",
    "/where-to-find",
    "/where-to-find/",
    "/schedule",
    "/schedule/",
    "/reunioes",
    "/reuniões",
    "/reuniones",
    "/reunions",
    "/horario",
    "/horários",
    "/horarios",
    "/spotkania",
    "/mityngi",
    "/mitingi",
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
                context = await browser.new_context(
                    user_agent=self.user_agent,
                    ignore_https_errors=True,
                )
                page = await context.new_page()
                page.set_default_timeout(self.settings.page_timeout_ms)
                remembered_urls = remembered_meeting_page_urls(self.source)
                queue = initial_crawl_queue(
                    self.source.url,
                    remembered_urls=remembered_urls,
                )
                visited: set[str] = set()
                visited_final: set[str] = set()
                common_meeting_paths_enqueued = False
                broad_fallback_allowed = False
                broad_fallback_enqueued = False
                guessed_common_not_found_count = 0
                broad_fallback: list[dict[str, str]] = []
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
                    try:
                        scraped = await asyncio.wait_for(
                            self._scrape_page(
                                page,
                                normalized,
                                allow_heuristic_search_form=depth >= 0,
                            ),
                            timeout=_page_hard_timeout_seconds(self.settings),
                        )
                    except Exception:
                        if depth < 0:
                            continue
                        raise
                    final_normalized = normalize_crawl_url(scraped.final_url)
                    if final_normalized in visited_final:
                        continue
                    visited_final.add(final_normalized)
                    pages.append(scraped)
                    has_pending_remembered_page = _has_pending_remembered_page(queue)
                    if depth < 0:
                        if should_stop_after_remembered_page(
                            scraped,
                            self.source,
                            pending_queue=queue,
                        ):
                            break
                        if not scraped.extracted:
                            continue
                    if (
                        broad_fallback_allowed
                        and is_common_meeting_path(self.source.url, normalized)
                        and _looks_like_not_found_page(scraped)
                        and not scraped.extracted
                    ):
                        guessed_common_not_found_count += 1
                        if guessed_common_not_found_count >= 2:
                            queue = _without_common_meeting_path_links(queue, self.source.url)
                            broad_fallback_enqueued = True
                            broad_fallback = []
                    if self.source.source_type == SourceType.WORLD_SERVICE_LISTING:
                        if (
                            not has_pending_remembered_page
                            and should_stop_after_page(scraped, self.settings)
                        ):
                            break
                        continue
                    if depth >= 0 and should_stop_after_empty_meeting_directory(
                        scraped,
                        self.settings,
                    ):
                        break
                    if depth >= self.settings.max_depth:
                        if should_stop_after_page(
                            scraped,
                            self.settings,
                            pending_queue=queue,
                        ):
                            break
                        continue
                    links = await _page_links(page, scraped.final_url)
                    prioritized = prioritize_links(self.source.url, links)
                    if (
                        not has_pending_remembered_page
                        and should_stop_after_page(
                            scraped,
                            self.settings,
                            prioritized_links=prioritized,
                            pending_queue=queue,
                        )
                    ):
                        break
                    if prioritized:
                        for link in prioritized:
                            link_url = normalize_crawl_url(link["url"])
                            if link_url not in visited:
                                queue.append((link_url, depth + 1))
                    elif depth == 0 and not common_meeting_paths_enqueued:
                        broad_fallback_allowed = True
                        broad_fallback = fallback_links(self.source.url, links)
                        prioritized = common_meeting_path_links(self.source.url)
                        common_meeting_paths_enqueued = True
                        for link in prioritized:
                            link_url = normalize_crawl_url(link["url"])
                            if link_url not in visited:
                                queue.append((link_url, depth + 1))
                    if (
                        not queue
                        and broad_fallback_allowed
                        and broad_fallback
                        and not broad_fallback_enqueued
                        and not any(item.extracted_count for item in pages)
                    ):
                        broad_fallback_enqueued = True
                        for link in broad_fallback:
                            link_url = normalize_crawl_url(link["url"])
                            if link_url not in visited:
                                queue.append((link_url, 1))
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

    async def _scrape_page(
        self,
        page: Any,
        url: str,
        *,
        allow_heuristic_search_form: bool = True,
    ) -> ScrapedPage:
        if _looks_like_downloadable_meeting_list_url(url):
            downloaded = await _extract_meetings_from_downloadable_pdf(
                page,
                url,
                self.source.config,
            )
            if downloaded is not None:
                downloaded_html, downloaded_extracted = downloaded
                return ScrapedPage(
                    url=url,
                    final_url=url,
                    title="Downloaded meeting list",
                    html=downloaded_html,
                    page_score=0.85,
                    page_signals=["downloaded_meeting_list_pdf"],
                    actions=[
                        BrowserActionTrace(
                            action="downloaded_meeting_list_pdf",
                            value=url,
                            status="succeeded",
                            message=f"extracted {len(downloaded_extracted)} records",
                        )
                    ],
                    extracted=downloaded_extracted,
                )
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
        pre_interaction_html = await _safe_page_content(page)
        pre_interaction_url = str(page.url)
        pre_interaction_score = score_html(pre_interaction_url, pre_interaction_html)
        pre_interaction_links = prioritize_links(
            self.source.url,
            await _page_links(page, pre_interaction_url),
        )
        traces.extend(
            await perform_heuristic_interactions(
                page,
                self.source,
                self.settings,
                allow_search_form=should_allow_heuristic_search_form(
                    pre_interaction_url,
                    pre_interaction_score,
                    pre_interaction_links,
                    requested=allow_heuristic_search_form,
                ),
            )
        )
        wait_for_selector = browser_config.get("wait_for_selector")
        if wait_for_selector:
            await page.wait_for_selector(str(wait_for_selector))
        with suppress(Exception):
            await page.wait_for_load_state("domcontentloaded", timeout=2_000)
        html = await _safe_page_content(page)
        final_url = str(page.url)
        body_text = await _safe_body_text(page)
        if _looks_like_deferred_render_page(html) and len(body_text.strip()) < 400:
            body_text = await _wait_for_rendered_body_text(page, self.settings)
            html = await _safe_page_content(page)
        title = await page.title()
        if wix_collection_text := await _wix_dynamic_collection_text(page):
            html = _html_with_rendered_text(html, wix_collection_text)
        page_score = score_html(final_url, html)
        extracted: list[ExtractedMeeting] = []
        tsml_feed_url = _tsml_json_feed_url_from_html(html, final_url)
        if (
            tsml_feed_url is not None
            and self.source.source_type != SourceType.WORLD_SERVICE_LISTING
            and (
                is_allowed_url(self.source.url, tsml_feed_url)
                or _looks_like_tsml_json_feed_url(tsml_feed_url)
            )
        ):
            feed_html = await _fetch_json_feed_text(page, tsml_feed_url)
            if feed_html:
                feed_extracted = extract_meetings_from_html(
                    feed_html,
                    source_page_url=tsml_feed_url,
                    source_config=self.source.config,
                )
                if feed_extracted:
                    feed_score = score_html(tsml_feed_url, feed_html)
                    traces.append(
                        BrowserActionTrace(
                            action="tsml_json_feed",
                            selector="link[rel~='alternate'][type='application/json']",
                            value=tsml_feed_url,
                            status="succeeded",
                            message=f"extracted {len(feed_extracted)} records",
                        )
                    )
                    html = feed_html
                    final_url = tsml_feed_url
                    page_score = PageScore(
                        score=max(page_score.score, feed_score.score, 0.9),
                        signals=_dedupe_strings(
                            [*page_score.signals, *feed_score.signals, "tsml_json_feed"]
                        ),
                        negative_signals=feed_score.negative_signals,
                    )
                    extracted = feed_extracted
        if not extracted:
            extracted = extract_meetings_from_html(
                html,
                source_page_url=final_url,
                source_config=self.source.config,
            )
        if not extracted and body_text.strip():
            rendered_html = _html_with_rendered_text(html, body_text)
            rendered_page_score = score_html(final_url, rendered_html)
            rendered_extracted = extract_meetings_from_html(
                rendered_html,
                source_page_url=final_url,
                source_config=self.source.config,
            )
            if rendered_extracted:
                html = rendered_html
                page_score = rendered_page_score
                extracted = rendered_extracted
        if not extracted and self.source.source_type != SourceType.WORLD_SERVICE_LISTING:
            embed_result = await _extract_meetings_from_embeds(
                page,
                final_url,
                html,
                self.source.config,
            )
            if embed_result is not None:
                embed_url, embed_html, embed_extracted, action = embed_result
                traces.append(
                    BrowserActionTrace(
                        action=action,
                        selector="iframe[src], embed[src], object[data]",
                        value=embed_url,
                        status="succeeded",
                        message=f"extracted {len(embed_extracted)} records",
                    )
                )
                html = embed_html
                final_url = embed_url
                page_score = PageScore(
                    score=max(page_score.score, 0.85),
                    signals=_dedupe_strings([*page_score.signals, action]),
                    negative_signals=page_score.negative_signals,
                )
                extracted = embed_extracted
        if not extracted and self.source.source_type != SourceType.WORLD_SERVICE_LISTING:
            pdf_result = await _extract_meetings_from_linked_pdfs(
                page,
                final_url,
                self.source.config,
            )
            if pdf_result is not None:
                pdf_url, pdf_html, pdf_extracted = pdf_result
                traces.append(
                    BrowserActionTrace(
                        action="pdf_meeting_list",
                        selector="a[href$='.pdf']",
                        value=pdf_url,
                        status="succeeded",
                        message=f"extracted {len(pdf_extracted)} records",
                    )
                )
                html = pdf_html
                final_url = pdf_url
                page_score = PageScore(
                    score=max(page_score.score, 0.85),
                    signals=_dedupe_strings([*page_score.signals, "pdf_meeting_list"]),
                    negative_signals=page_score.negative_signals,
                )
                extracted = pdf_extracted
        if (
            self.source.source_type != SourceType.WORLD_SERVICE_LISTING
            and page_score.score < self.settings.local_page_min_extraction_score
        ):
            extracted = []
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


def initial_crawl_queue(
    source_url: str,
    *,
    remembered_urls: list[str] | None = None,
) -> deque[tuple[str, int]]:
    queue: deque[tuple[str, int]] = deque()
    seen: set[str] = set()
    for url in remembered_urls or []:
        normalized = normalize_crawl_url(url)
        if normalized in seen or not is_allowed_url(source_url, normalized):
            continue
        seen.add(normalized)
        queue.append((normalized, -1))
    normalized_source = normalize_crawl_url(source_url)
    if normalized_source not in seen:
        queue.append((normalized_source, 0))
    return queue


def remembered_meeting_page_urls(source: Source) -> list[str]:
    if _is_najapan_area_source(source.url):
        return []
    scrape_config = source.config.get("scrape")
    if not isinstance(scrape_config, dict):
        return []
    urls: list[str] = []
    pages = scrape_config.get("successful_pages")
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            url = page.get("url")
            if isinstance(url, str) and url.strip():
                urls.append(url.strip())
    legacy_urls = scrape_config.get("successful_page_urls")
    if isinstance(legacy_urls, list):
        urls.extend(url.strip() for url in legacy_urls if isinstance(url, str) and url.strip())
    url = scrape_config.get("last_successful_page_url")
    if isinstance(url, str) and url.strip():
        urls.append(url.strip())
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized = normalize_crawl_url(url)
        if normalized in seen:
            continue
        if not _is_relevant_source_branch_link(source.url, normalized):
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped[:5]


def _is_najapan_area_source(source_url: str) -> bool:
    parsed = urlparse(source_url)
    if not (parsed.hostname or "").endswith("najapan.org"):
        return False
    parts = [part for part in (parsed.path or "").strip("/").split("/") if part]
    return len(parts) >= 2 and parts[0] == "meeting"


def remembered_page_expected_records(source: Source, page_url: str) -> int | None:
    scrape_config = source.config.get("scrape")
    if not isinstance(scrape_config, dict):
        return None
    normalized_page_url = normalize_crawl_url(page_url)
    pages = scrape_config.get("successful_pages")
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            url = page.get("url")
            if not isinstance(url, str):
                continue
            if normalize_crawl_url(url) != normalized_page_url:
                continue
            records = page.get("records_extracted")
            if isinstance(records, int) and records > 0:
                return records
    url = scrape_config.get("last_successful_page_url")
    records = scrape_config.get("last_successful_page_records")
    if (
        isinstance(url, str)
        and normalize_crawl_url(url) == normalized_page_url
        and isinstance(records, int)
        and records > 0
    ):
        return records
    return None


def common_meeting_path_links(source_url: str) -> list[dict[str, str]]:
    parsed = urlparse(source_url)
    root_url = f"{parsed.scheme}://{parsed.netloc}/"
    links: list[dict[str, str]] = []
    seen = {normalize_crawl_url(source_url)}
    seen_paths = {_normalized_path_key(source_url)}
    for path in COMMON_MEETING_PATHS:
        candidate_url = normalize_crawl_url(urljoin(root_url, path))
        path_key = _normalized_path_key(candidate_url)
        if (
            candidate_url in seen
            or path_key in seen_paths
            or not is_allowed_url(source_url, candidate_url)
        ):
            continue
        seen.add(candidate_url)
        seen_paths.add(path_key)
        links.append({"url": candidate_url, "text": path.strip("/").replace("-", " ")})
    return links


def is_common_meeting_path(source_url: str, candidate_url: str) -> bool:
    source = urlparse(source_url)
    candidate = urlparse(candidate_url)
    if candidate.hostname != source.hostname:
        return False
    common_keys = {
        _normalized_path_key(urljoin(f"{source.scheme}://{source.netloc}/", path))
        for path in COMMON_MEETING_PATHS
    }
    return _normalized_path_key(candidate_url) in common_keys


def is_allowed_url(source_url: str, candidate_url: str) -> bool:
    source_host = urlparse(source_url).hostname or ""
    candidate = urlparse(candidate_url)
    if candidate.scheme not in {"http", "https"}:
        return False
    if normalize_crawl_url(candidate_url) == normalize_crawl_url(source_url):
        return True
    if candidate.path.lower().endswith(SKIP_PATH_SUFFIXES):
        return False
    if any(marker in candidate.path.lower() for marker in SKIP_PATH_MARKERS):
        return False
    query_keys = {key.lower() for key, _value in parse_qsl(candidate.query, keep_blank_values=True)}
    if query_keys.intersection(SKIP_QUERY_KEYS):
        return False
    candidate_host = candidate.hostname or ""
    if candidate_host == source_host:
        return True
    source_root = ".".join(source_host.split(".")[-2:])
    candidate_root = ".".join(candidate_host.split(".")[-2:])
    return bool(source_root and source_root == candidate_root)


def _normalized_path_key(url: str) -> str:
    path = urlparse(url).path or "/"
    return path.rstrip("/").lower() or "/"


def _without_common_meeting_path_links(
    queue: deque[tuple[str, int]],
    source_url: str,
) -> deque[tuple[str, int]]:
    return deque(
        (url, depth)
        for url, depth in queue
        if not is_common_meeting_path(source_url, normalize_crawl_url(url))
    )


def _has_pending_remembered_page(queue: deque[tuple[str, int]]) -> bool:
    return any(depth < 0 for _url, depth in queue)


def _looks_like_not_found_page(page: ScrapedPage) -> bool:
    title = (page.title or "").lower()
    if any(
        phrase in title
        for phrase in (
            "404",
            "page not found",
            "not found",
            "page non trouvée",
            "seite nicht gefunden",
            "side ikke fundet",
            "stránka nenalezena",
            "страница не найдена",
        )
    ):
        return True
    return "404" in page.final_url.lower()


def prioritize_links(source_url: str, links: list[dict[str, str]]) -> list[dict[str, str]]:
    allowed = [
        link
        for link in links
        if is_allowed_url(source_url, link["url"])
        and _is_relevant_source_branch_link(source_url, link["url"])
    ]
    scored = [
        (link, _priority_score(source_url, link))
        for link in allowed
    ]
    positive = [(link, score) for link, score in scored if score > 0]
    return sorted(
        [link for link, _score in positive],
        key=lambda link: _priority_score(source_url, link),
        reverse=True,
    )


def _priority_score(source_url: str, link: dict[str, str]) -> float:
    score = score_link(link["url"], link.get("text", "")).score
    if _is_child_path(source_url, link["url"]):
        score += 0.4
    return score


def _is_child_path(source_url: str, candidate_url: str) -> bool:
    source = urlparse(source_url)
    candidate = urlparse(candidate_url)
    if candidate.hostname != source.hostname:
        return False
    source_path = (source.path or "/").rstrip("/")
    candidate_path = (candidate.path or "/").rstrip("/")
    if not source_path or source_path == "/" or candidate_path == source_path:
        return False
    return candidate_path.startswith(f"{source_path}/")


def _is_relevant_source_branch_link(source_url: str, candidate_url: str) -> bool:
    source = urlparse(source_url)
    candidate = urlparse(candidate_url)
    if not (source.hostname or "").endswith("najapan.org"):
        return True
    source_parts = [part for part in (source.path or "").strip("/").split("/") if part]
    if len(source_parts) < 2 or source_parts[0] != "meeting":
        return True
    area_path = f"/meeting/{source_parts[1]}".rstrip("/")
    candidate_path = (candidate.path or "/").rstrip("/")
    return candidate_path == area_path or candidate_path.startswith(f"{area_path}/")


def fallback_links(source_url: str, links: list[dict[str, str]]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for link in links:
        if not is_allowed_url(source_url, link["url"]):
            continue
        score = score_link(link["url"], link.get("text", ""))
        if score.score > 0 or score.negative_signals:
            continue
        candidates.append(link)
    return candidates


def should_stop_after_page(
    page: ScrapedPage,
    settings: CrawlSettings,
    *,
    prioritized_links: list[dict[str, str]] | None = None,
    pending_queue: deque[tuple[str, int]] | None = None,
) -> bool:
    if not settings.stop_after_successful_meeting_page:
        return False
    if page.extracted_count > 0 and _is_landing_page_url(page.final_url):
        return not _has_deeper_meeting_directory_link(
            page.final_url,
            prioritized_links or [],
        )
    if page.extracted_count > 0 and _has_pending_meeting_branch(page.final_url, pending_queue):
        return False
    return (
        page.extracted_count >= settings.successful_meeting_page_min_records
        and (
            page.page_score >= settings.successful_meeting_page_min_score
            or page.page_score >= 0.5
        )
    )


def should_stop_after_remembered_page(
    page: ScrapedPage,
    source: Source,
    *,
    pending_queue: deque[tuple[str, int]] | None = None,
) -> bool:
    if page.extracted_count <= 0 or _has_pending_remembered_page(pending_queue or deque()):
        return False
    expected_records = remembered_page_expected_records(source, page.final_url)
    if expected_records is None:
        return True
    if expected_records <= 2:
        return True
    minimum_records = max(1, int(expected_records * 0.75))
    return page.extracted_count >= minimum_records


def should_stop_after_empty_meeting_directory(
    page: ScrapedPage,
    settings: CrawlSettings,
) -> bool:
    if page.extracted_count > 0 or _is_landing_page_url(page.final_url):
        return False
    if page.page_score < settings.successful_meeting_page_min_score:
        return False
    stop_signals = {
        "strong_public_meeting_directory",
        "meeting_form",
        "meeting_table",
        "tsml_json_feed",
    }
    return bool(stop_signals.intersection(page.page_signals))


def should_allow_heuristic_search_form(
    page_url: str,
    page_score: PageScore,
    prioritized_links: list[dict[str, str]],
    *,
    requested: bool,
) -> bool:
    if not requested:
        return False
    if not _has_deeper_meeting_directory_link(page_url, prioritized_links):
        return True
    directory_signals = {
        "strong_public_meeting_directory",
        "meeting_form",
        "meeting_table",
        "day_and_time_text",
    }
    if directory_signals.intersection(page_score.signals):
        return False
    return not any(
        signal.startswith(("url_or_text:", "text:", "body:"))
        and "meeting" in signal
        for signal in page_score.signals
    )


def _is_landing_page_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.path or "/").rstrip("/") in {"", "/"}


def _has_deeper_meeting_directory_link(
    page_url: str,
    prioritized_links: list[dict[str, str]],
) -> bool:
    current = normalize_crawl_url(page_url)
    for link in prioritized_links:
        link_url = normalize_crawl_url(link["url"])
        if normalize_crawl_url(link_url) == current:
            continue
        if _looks_like_deeper_meeting_directory_link(link_url, link.get("text", "")):
            return True
    return False


def _has_pending_meeting_branch(
    page_url: str,
    pending_queue: deque[tuple[str, int]] | None,
) -> bool:
    if pending_queue is None:
        return False
    current = normalize_crawl_url(page_url)
    for queued_url, _depth in pending_queue:
        candidate = normalize_crawl_url(queued_url)
        if candidate == current:
            continue
        if _looks_like_pending_meeting_branch(candidate):
            return True
    return False


def _looks_like_pending_meeting_branch(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()
    if not path:
        return False
    if _looks_like_deeper_meeting_directory_link(url, ""):
        return True
    path_parts = [part for part in path.split("/") if part]
    return bool(
        path_parts
        and path_parts[0]
        in {"meeting", "meetings", "meeting-schedule", "groups", "aa-groups", "a-a-groups"}
    )


def _looks_like_deeper_meeting_directory_link(url: str, text: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()
    if not path:
        return False
    score = score_link(url, text)
    if "strong_public_meeting_directory" in score.signals:
        return True
    last_segment = path.rsplit("/", 1)[-1]
    directory_terms = (
        "meeting",
        "meetings",
        "group",
        "groups",
        "schedule",
        "møteliste",
        "moteliste",
    )
    if score.score >= 0.35 and any(term in path for term in directory_terms):
        return True
    return score.score >= 0.5 and any(term in last_segment for term in directory_terms)


def _page_hard_timeout_seconds(settings: CrawlSettings) -> float:
    timeout_ms = (
        settings.page_timeout_ms
        + settings.deferred_render_timeout_ms
        + (settings.action_timeout_ms * min(settings.max_actions_per_page, 4))
        + 10_000
    )
    return max(20.0, timeout_ms / 1000)


def _tsml_json_feed_url_from_html(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select("link[rel~='alternate'][type='application/json'][href]"):
        href = str(link.get("href") or "")
        title = str(link.get("title") or "").lower()
        if not href:
            continue
        if "action=meetings" in href.lower() or "meetings feed" in title:
            feed_url = normalize_crawl_url(urljoin(base_url, href))
            return _tsml_feed_url_with_page_filters(feed_url, base_url)
    for element in soup.select("[data-src]"):
        data_src = str(element.get("data-src") or "")
        if data_src and _looks_like_tsml_json_feed_url(data_src):
            return normalize_crawl_url(urljoin(base_url, data_src))
    return None


def _tsml_feed_url_with_page_filters(feed_url: str, page_url: str) -> str:
    page_query = parse_qsl(urlparse(page_url).query, keep_blank_values=False)
    feed_query = parse_qsl(urlparse(feed_url).query, keep_blank_values=True)
    existing_keys = {key.lower() for key, _value in feed_query}
    for key, value in page_query:
        filter_key = key.lower().removeprefix("tsml-")
        if filter_key == key.lower() or filter_key not in {
            "attendance_option",
            "district",
            "region",
        }:
            continue
        if value.strip().lower() in {"", "all", "any"} or filter_key in existing_keys:
            continue
        feed_query.append((filter_key, value))
        existing_keys.add(filter_key)
    if not feed_query:
        return feed_url
    parsed_feed = urlparse(feed_url)
    return urlunparse(parsed_feed._replace(query=urlencode(feed_query)))


def _tsml_json_feed_url_from_page_url(page_url: str) -> str | None:
    parsed = urlparse(page_url)
    if "tsml-" not in parsed.query.lower():
        return None
    feed_url = urlunparse(
        parsed._replace(
            path="/wp-admin/admin-ajax.php",
            params="",
            query="action=meetings",
            fragment="",
        )
    )
    return normalize_crawl_url(_tsml_feed_url_with_page_filters(feed_url, page_url))


def _looks_like_tsml_json_feed_url(url: str) -> bool:
    lowered = url.lower()
    return "action=meetings" in lowered or "meetings-tsml" in lowered


async def _fetch_json_feed_text(page: Any, url: str) -> str:
    try:
        response = await page.evaluate(
            """
            async url => {
              const response = await fetch(url, {
                credentials: 'same-origin',
                headers: { Accept: 'application/json' }
              });
              return {
                status: response.status,
                contentType: response.headers.get('content-type') || '',
                text: await response.text()
              };
            }
            """,
            url,
        )
    except Exception:
        response = None
    if isinstance(response, dict) and response.get("status") == 200:
        text = response.get("text")
        return text if isinstance(text, str) else ""
    request = getattr(getattr(page, "context", None), "request", None)
    if request is None:
        return ""
    try:
        api_response = await request.get(
            url,
            headers={"Accept": "application/json"},
            timeout=15_000,
        )
        if getattr(api_response, "status", None) != 200:
            return ""
        text = await api_response.text()
    except Exception:
        return ""
    return text if isinstance(text, str) else ""


async def _extract_meetings_from_linked_pdfs(
    page: Any,
    base_url: str,
    source_config: dict[str, Any],
) -> tuple[str, str, list[ExtractedMeeting]] | None:
    links = _meeting_pdf_links(await _page_links(page, base_url))
    if not links:
        return None
    fetches = await asyncio.gather(
        *[_fetch_pdf_text(page, link["url"]) for link in links[:2]],
        return_exceptions=True,
    )
    for link, fetched in zip(links, fetches, strict=False):
        if not isinstance(fetched, str) or not fetched.strip():
            continue
        pdf_html = _html_with_pdf_text(fetched)
        extracted = extract_meetings_from_html(
            pdf_html,
            source_page_url=link["url"],
            source_config=source_config,
        )
        if extracted:
            return link["url"], pdf_html, extracted
    return None


async def _extract_meetings_from_downloadable_pdf(
    page: Any,
    url: str,
    source_config: dict[str, Any],
) -> tuple[str, list[ExtractedMeeting]] | None:
    text = await _fetch_pdf_text(page, url)
    if not text.strip():
        return None
    html = _html_with_pdf_text(text)
    extracted = extract_meetings_from_html(
        html,
        source_page_url=url,
        source_config=source_config,
    )
    if not extracted:
        return None
    return html, extracted


async def _extract_meetings_from_embeds(
    page: Any,
    base_url: str,
    html: str,
    source_config: dict[str, Any],
) -> tuple[str, str, list[ExtractedMeeting], str] | None:
    embed_urls = _embedded_urls_from_html(html, base_url)
    for url in embed_urls:
        if _is_nz_picker_url(url):
            picker_html = await _fetch_nz_picker_meetings_html(page, url)
            if not picker_html:
                continue
            extracted = extract_meetings_from_html(
                picker_html,
                source_page_url=url,
                source_config=source_config,
            )
            if extracted:
                return url, picker_html, extracted, "nz_picker_embed"
    calendar_urls = _google_calendar_ics_urls(embed_urls)
    if calendar_urls:
        fetched = await asyncio.gather(
            *[_fetch_embed_text(page, url, "text/calendar") for url in calendar_urls],
            return_exceptions=True,
        )
        for url, text in zip(calendar_urls, fetched, strict=False):
            if not isinstance(text, str) or not text.strip():
                continue
            extracted = _extract_google_calendar_ics_meetings(text, url)
            if extracted:
                return url, _html_with_rendered_text("", text), extracted, "google_calendar_ics"
    return None


def _embedded_urls_from_html(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()
    for tag in soup.select("iframe[src], embed[src], object[data]"):
        attr = "data" if tag.name == "object" else "src"
        raw_url = str(tag.get(attr) or "").strip()
        if not raw_url:
            continue
        url = normalize_crawl_url(urljoin(base_url, raw_url))
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _is_nz_picker_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname == "picker.nzna.org"


async def _fetch_nz_picker_meetings_html(page: Any, embed_url: str) -> str:
    parsed = urlparse(embed_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    pieces: list[str] = []
    for venue in ("in-person", "online"):
        url = f"{base_url}/{venue}/SHOW%20ALL/SHOW%20ALL/"
        text = await _fetch_embed_text(page, url, "application/json")
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        meetings = payload.get("meetings")
        if isinstance(meetings, str) and meetings.strip():
            pieces.append(meetings)
    if not pieces:
        return ""
    return "<html><body>" + "\n".join(pieces) + "</body></html>"


def _google_calendar_ics_urls(embed_urls: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for embed_url in embed_urls:
        parsed = urlparse(embed_url)
        host = parsed.hostname or ""
        if host not in {"calendar.google.com", "www.google.com", "google.com"}:
            continue
        if "/calendar/" not in parsed.path and "calendar" not in parsed.path:
            continue
        for key, value in parse_qsl(parsed.query, keep_blank_values=False):
            if key != "src":
                continue
            calendar_id = _decode_google_calendar_src(value)
            if not calendar_id:
                continue
            url = f"https://calendar.google.com/calendar/ical/{calendar_id}/public/basic.ics"
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


def _decode_google_calendar_src(value: str) -> str:
    if "@" in value:
        return value
    try:
        padded = value + "=" * ((4 - len(value) % 4) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode()).decode()
    except (ValueError, UnicodeDecodeError):
        return value
    return decoded if "@" in decoded else value


async def _fetch_embed_text(page: Any, url: str, accept: str) -> str:
    request = getattr(getattr(page, "context", None), "request", None)
    if request is None:
        return ""
    try:
        response = await request.get(
            url,
            headers={
                "Accept": accept,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=20_000,
        )
        if getattr(response, "status", None) != 200:
            return ""
        return str(await response.text())
    except Exception:
        return ""


def _extract_google_calendar_ics_meetings(
    ics_text: str,
    source_page_url: str,
) -> list[ExtractedMeeting]:
    events = _parse_ics_events(ics_text)
    meetings: list[ExtractedMeeting] = []
    calendar_timezone = _ics_calendar_timezone(ics_text)
    for row_index, event in enumerate(events):
        if not _is_recurring_meeting_event(event):
            continue
        day = _ics_event_day(event)
        time = _ics_event_time(event)
        name = _clean_ics_text(event.get("SUMMARY", ""))
        location = _clean_ics_text(event.get("LOCATION", ""))
        if not day or not time or not name or not location:
            continue
        payload: dict[str, Any] = {
            "source_record_id": event.get("UID") or f"{name}-{day}-{time}",
            "day": day,
            "time": time,
            "name": name,
            "address_line1": location,
        }
        timezone = event.get("DTSTART_TZID") or calendar_timezone
        if timezone:
            payload["timezone"] = timezone
        description = _clean_ics_text(event.get("DESCRIPTION", ""))
        if description:
            payload["notes"] = description
            if "zoom" in description.lower():
                payload["phone_join_info"] = description
        confidence, signals = confidence_for_payload(
            payload,
            method="google_calendar_ics",
            page_score=0.9,
            repeated_structure=True,
        )
        meetings.append(
            ExtractedMeeting(
                payload={**payload, "row_index": row_index},
                method="google_calendar_ics",
                confidence=max(confidence, 0.82),
                source_page_url=source_page_url,
                signals=signals,
                selector_hint="google_calendar_ics",
            )
        )
    return meetings


def _parse_ics_events(ics_text: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in _unfold_ics_lines(ics_text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        raw_key, value = line.split(":", 1)
        key_parts = raw_key.split(";")
        key = key_parts[0]
        current[key] = value
        if key == "DTSTART":
            for part in key_parts[1:]:
                if part.startswith("TZID="):
                    current["DTSTART_TZID"] = part.removeprefix("TZID=")
    return events


def _unfold_ics_lines(ics_text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in ics_text.replace("\r\n", "\n").split("\n"):
        if raw_line.startswith((" ", "\t")) and lines:
            lines[-1] += raw_line[1:]
        elif raw_line:
            lines.append(raw_line)
    return lines


def _ics_calendar_timezone(ics_text: str) -> str:
    for line in _unfold_ics_lines(ics_text):
        if line.startswith("X-WR-TIMEZONE:"):
            return line.split(":", 1)[1]
    return ""


def _is_recurring_meeting_event(event: dict[str, str]) -> bool:
    rrule = event.get("RRULE", "")
    summary = _clean_ics_text(event.get("SUMMARY", "")).lower()
    if "FREQ=WEEKLY" not in rrule:
        return False
    if not _rrule_is_current(rrule):
        return False
    negative_terms = (
        "anniversary",
        "area service",
        "asc",
        "bbq",
        "campout",
        "cancelled",
        "convention",
        "dance",
        "event",
        "fundraiser",
        "speaker jam",
        "temporarily",
        "workshop",
    )
    return not any(term in summary for term in negative_terms)


def _rrule_is_current(rrule: str) -> bool:
    match = re.search(r"(?:^|;)UNTIL=(\d{8})(?:T\d{6}Z?)?", rrule)
    if match is None:
        return True
    until = datetime.strptime(match.group(1), "%Y%m%d").replace(tzinfo=UTC)
    return until.date() >= datetime.now(UTC).date()


def _ics_event_day(event: dict[str, str]) -> str:
    byday = re.search(r"(?:^|;)BYDAY=([^;]+)", event.get("RRULE", ""))
    if byday is not None:
        first_day = byday.group(1).split(",", 1)[0]
        return {
            "SU": "Sunday",
            "MO": "Monday",
            "TU": "Tuesday",
            "WE": "Wednesday",
            "TH": "Thursday",
            "FR": "Friday",
            "SA": "Saturday",
        }.get(first_day, "")
    return ""


def _ics_event_time(event: dict[str, str]) -> str:
    value = event.get("DTSTART", "")
    match = re.search(r"T(\d{2})(\d{2})", value)
    if match is None:
        return ""
    return f"{int(match.group(1))}:{match.group(2)}"


def _clean_ics_text(text: str) -> str:
    cleaned = text.replace("\\n", " ")
    cleaned = cleaned.replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    return " ".join(cleaned.split())


async def _fetch_pdf_text(page: Any, url: str) -> str:
    request = getattr(getattr(page, "context", None), "request", None)
    if request is None:
        return ""
    try:
        response = await request.get(
            url,
            headers={"Accept": "application/pdf"},
            timeout=20_000,
        )
        if getattr(response, "status", None) != 200:
            return ""
        headers = getattr(response, "headers", {})
        content_type = str(headers.get("content-type") if isinstance(headers, dict) else "").lower()
        if "pdf" not in content_type and not urlparse(url).path.lower().endswith(".pdf"):
            return ""
        content = await response.body()
    except Exception:
        return ""
    return extract_pdf_text(bytes(content))


def _meeting_pdf_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in links:
        url = normalize_crawl_url(link["url"])
        if url in seen or not _looks_like_meeting_pdf_link(url, link.get("text", "")):
            continue
        seen.add(url)
        candidates.append({"url": url, "text": link.get("text", "")})
    return candidates


def _looks_like_meeting_pdf_link(url: str, text: str) -> bool:
    parsed = urlparse(url)
    if not parsed.path.lower().endswith(".pdf"):
        return False
    haystack = f"{text} {parsed.path}".replace("_", " ").replace("-", " ").lower()
    negative_terms = (
        "agenda",
        "annual",
        "booklet",
        "bulletin",
        "bylaw",
        "campout",
        "convention",
        "event",
        "flyer",
        "guideline",
        "introduction to na meetings",
        "ip 29",
        "ip-29",
        "literature",
        "minutes",
        "newsletter",
        "newsgram",
        "policy",
        "poster",
        "report",
        "service",
        "speaker jam",
        "workshop",
        "en3129",
    )
    if any(term in haystack for term in negative_terms):
        return False
    positive_terms = (
        "current meeting list",
        "meeting list",
        "meeting schedule",
        "meetings updated",
        "meetings update",
        "na meeting",
        "schedule",
        "where and when",
        "ミーティングリスト",
        "ミーティング情報",
        "会場案内",
    )
    return any(term in haystack for term in positive_terms)


def _looks_like_downloadable_meeting_list_url(url: str) -> bool:
    query_keys = {key.lower() for key, _value in parse_qsl(urlparse(url).query)}
    return bool(query_keys.intersection(SKIP_QUERY_KEYS))


async def _page_links(page: Any, base_url: str) -> list[dict[str, str]]:
    raw_links = await page.eval_on_selector_all(
        "a[href], link[rel~='alternate'][type='application/json'][href]",
        """
        links => links.map(link => ({
          url: link.getAttribute('href'),
          text: link.textContent || link.getAttribute('title') || link.getAttribute('type') || ''
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
        normalized_url = normalize_crawl_url(urljoin(base_url, str(href)))
        normalized_url = _tsml_json_feed_url_from_page_url(normalized_url) or normalized_url
        links.append(
            {
                "url": normalized_url,
                "text": str(raw_link.get("text") or ""),
            }
        )
    return links


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


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


async def _safe_body_text(page: Any) -> str:
    texts: list[str] = []
    for frame in getattr(page, "frames", [page]):
        try:
            text = str(await frame.locator("body").inner_text(timeout=1_000))
        except Exception:
            continue
        if text.strip():
            texts.append(text)
    return "\n".join(texts)


async def _wait_for_rendered_body_text(page: Any, settings: CrawlSettings) -> str:
    deadline_ms = max(0, settings.deferred_render_timeout_ms)
    elapsed_ms = 0
    body_text = await _safe_body_text(page)
    while elapsed_ms < deadline_ms:
        if len(body_text.strip()) >= 400:
            return body_text
        await page.wait_for_timeout(500)
        elapsed_ms += 500
        body_text = await _safe_body_text(page)
    return body_text


def _looks_like_deferred_render_page(html: str) -> bool:
    lowered = html.lower()
    return (
        "wix-viewer-model" in lowered
        or "wix-essential-viewer-model" in lowered
        or "wix-thunderbolt" in lowered
    )


def _html_with_rendered_text(html: str, body_text: str) -> str:
    rendered = escape(body_text)
    return f'{html}\n<div data-rendered-text-fallback="true"><pre>{rendered}</pre></div>'


def _html_with_pdf_text(pdf_text: str) -> str:
    rendered = escape(pdf_text)
    return (
        f'<html><body><div data-pdf-text-fallback="true">'
        f"<pre>{rendered}</pre></div></body></html>"
    )


async def _wix_dynamic_collection_text(page: Any) -> str:
    collection_config = await _wix_dynamic_collection_config(page)
    if collection_config is None:
        return ""
    collection = collection_config["collection"]
    grid_app_id = collection_config["grid_app_id"]
    data_items: list[dict[str, Any]] = []
    offset = 0
    page_size = 100
    while True:
        response = await _wix_cloud_data_query(
            page,
            collection=collection,
            grid_app_id=grid_app_id,
            sort=collection_config["sort"],
            offset=offset,
            limit=page_size,
        )
        items = response.get("dataItems")
        if not isinstance(items, list):
            break
        data_items.extend(item for item in items if isinstance(item, dict))
        paging = response.get("pagingMetadata")
        has_next = isinstance(paging, dict) and paging.get("hasNext") is True
        if len(items) < page_size or not has_next:
            break
        offset += len(items)
        if offset >= 2_000:
            break
    return _wix_data_items_to_text(data_items)


async def _wix_dynamic_collection_config(page: Any) -> dict[str, Any] | None:
    config = await page.evaluate(
        """
        () => {
          const model = window.viewerModel;
          const dynamicPages = model?.siteFeaturesConfigs?.dynamicPages?.prefixToRouterFetchData;
          if (!dynamicPages) return null;
          const path = window.location.pathname.replace(/^\\/+|\\/+$/g, "");
          const entries = Object.entries(dynamicPages)
            .filter(([prefix]) => path === prefix || path.startsWith(prefix + "/"))
            .sort((a, b) => b[0].length - a[0].length);
          if (!entries.length) return null;
          const data = entries[0][1];
          const pattern = data?.optionsData?.bodyData?.config?.patterns?.["/"];
          const collection = pattern?.config?.collection;
          if (!collection) return null;
          const params = new URLSearchParams(data?.urlData?.queryParams || "");
          const gridAppId = params.get("gridAppId")
            || model?.siteFeaturesConfigs?.dataWixCodeSdk?.gridAppId;
          if (!gridAppId) return null;
          return {
            collection,
            grid_app_id: gridAppId,
            sort: pattern?.config?.sort || []
          };
        }
        """
    )
    if not isinstance(config, dict):
        return None
    collection = config.get("collection")
    grid_app_id = config.get("grid_app_id")
    if not collection or not grid_app_id:
        return None
    return {
        "collection": str(collection),
        "grid_app_id": str(grid_app_id),
        "sort": _wix_query_sort(config.get("sort")),
    }


def _wix_query_sort(sort_config: object) -> list[dict[str, str]]:
    if not isinstance(sort_config, list):
        return []
    sort: list[dict[str, str]] = []
    for item in sort_config:
        if not isinstance(item, dict):
            continue
        for field_name, order in item.items():
            sort.append({"fieldName": str(field_name), "order": str(order).upper()})
            break
    return sort[:1]


async def _wix_cloud_data_query(
    page: Any,
    *,
    collection: str,
    grid_app_id: str,
    sort: list[dict[str, str]],
    offset: int,
    limit: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "dataCollectionId": collection,
        "environment": "LIVE",
        "appId": grid_app_id,
        "returnTotalCount": True,
        "query": {
            "filter": {},
            "paging": {"offset": offset, "limit": limit},
        },
    }
    if sort:
        payload["query"]["sort"] = sort
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    for _ in range(3):
        response = await page.evaluate(
            """
            async ({encoded, gridAppId}) => {
              const response = await fetch('/_api/cloud-data/v2/items/query?.r=' + encoded, {
                headers: {
                  'Content-Type': 'application/json',
                  'x-wix-grid-app-id': gridAppId
                }
              });
              return {status: response.status, text: await response.text()};
            }
            """,
            {"encoded": encoded, "gridAppId": grid_app_id},
        )
        if isinstance(response, dict) and response.get("status") == 200:
            text = response.get("text")
            if isinstance(text, str):
                parsed = json.loads(text)
                return parsed if isinstance(parsed, dict) else {}
        await page.wait_for_timeout(500)
    return {}


def _wix_data_items_to_text(data_items: list[dict[str, Any]]) -> str:
    if not data_items:
        return ""
    lines = ["Number found:"]
    for item in data_items:
        data = item.get("data") if isinstance(item.get("data"), dict) else item
        if not isinstance(data, dict):
            continue
        for field in (
            "title",
            "requirements",
            "time",
            "jobType1",
            "county",
            "jobDescription",
            "additionalTempMeetingInfo",
            "location",
            "openClosedMeeting",
        ):
            value = data.get(field)
            if value is None:
                continue
            text = _text_from_wix_value(value)
            if text:
                lines.append(text)
    return "\n".join(lines)


def _text_from_wix_value(value: object) -> str:
    text = str(value)
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text("\n", strip=True)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())

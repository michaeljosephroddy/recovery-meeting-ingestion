import asyncio
import base64
import json
from collections import deque
from contextlib import suppress
from hashlib import sha1
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urldefrag, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.adapters.base import AdapterPayloadError
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
from app.sources.registry import Source, SourceType

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
    "/meeting-locator",
    "/meeting-locator/",
    "/meeting-locations",
    "/meeting-locations/",
    "/locations",
    "/locations/",
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
                context = await browser.new_context(user_agent=self.user_agent)
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
                    scraped = await asyncio.wait_for(
                        self._scrape_page(page, normalized),
                        timeout=_page_hard_timeout_seconds(self.settings),
                    )
                    final_normalized = normalize_crawl_url(scraped.final_url)
                    if final_normalized in visited_final:
                        continue
                    visited_final.add(final_normalized)
                    pages.append(scraped)
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
                    has_pending_remembered_page = _has_pending_remembered_page(queue)
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
        seen.add(normalized)
        deduped.append(normalized)
    return deduped[:5]


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
    if candidate.path.lower().endswith(SKIP_PATH_SUFFIXES):
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
    allowed = [link for link in links if is_allowed_url(source_url, link["url"])]
    scored = [
        (link, score_link(link["url"], link.get("text", "")).score)
        for link in allowed
    ]
    positive = [(link, score) for link, score in scored if score > 0]
    return sorted(
        [link for link, _score in positive],
        key=lambda link: score_link(link["url"], link.get("text", "")).score,
        reverse=True,
    )


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

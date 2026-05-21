import base64
import json
from collections import deque
from contextlib import suppress
from hashlib import sha1
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse

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
from app.scraping.meeting_page_detector import score_html, score_link
from app.scraping.models import CrawlSettings, ScrapedPage, ScrapeSourceResult
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
    "/meetings/",
    "/meetings",
    "/meeting-schedule",
    "/meeting-schedule/",
    "/meetings-schedule",
    "/find-a-meeting",
    "/find-meeting",
    "/where-to-find",
    "/schedule",
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
                queue = initial_crawl_queue(self.source.url)
                visited: set[str] = set()
                visited_final: set[str] = set()
                common_meeting_paths_enqueued = False
                broad_fallback_allowed = False
                broad_fallback_enqueued = False
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
                    scraped = await self._scrape_page(page, normalized)
                    final_normalized = normalize_crawl_url(scraped.final_url)
                    if final_normalized in visited_final:
                        continue
                    visited_final.add(final_normalized)
                    pages.append(scraped)
                    if should_stop_after_page(scraped, self.settings):
                        break
                    if self.source.source_type == SourceType.WORLD_SERVICE_LISTING:
                        continue
                    if depth >= self.settings.max_depth:
                        continue
                    links = await _page_links(page, scraped.final_url)
                    prioritized = prioritize_links(self.source.url, links)
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


def initial_crawl_queue(source_url: str) -> deque[tuple[str, int]]:
    return deque([(source_url, 0)])


def common_meeting_path_links(source_url: str) -> list[dict[str, str]]:
    parsed = urlparse(source_url)
    root_url = f"{parsed.scheme}://{parsed.netloc}/"
    links: list[dict[str, str]] = []
    seen = {normalize_crawl_url(source_url)}
    for path in COMMON_MEETING_PATHS:
        candidate_url = normalize_crawl_url(urljoin(root_url, path))
        if candidate_url in seen or not is_allowed_url(source_url, candidate_url):
            continue
        seen.add(candidate_url)
        links.append({"url": candidate_url, "text": path.strip("/").replace("-", " ")})
    return links


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


def should_stop_after_page(page: ScrapedPage, settings: CrawlSettings) -> bool:
    if not settings.stop_after_successful_meeting_page:
        return False
    return (
        page.extracted_count >= settings.successful_meeting_page_min_records
        and page.page_score >= settings.successful_meeting_page_min_score
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


async def _safe_body_text(page: Any) -> str:
    try:
        return str(await page.locator("body").inner_text(timeout=1_000))
    except Exception:
        return ""


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

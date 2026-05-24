import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.config import Settings
from app.scraping.models import CrawlSettings
from app.scraping.service import scrape_source
from app.sources.registry import AdapterType, Source, SourceType

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="set RUN_BROWSER_TESTS=1 and install Playwright Chromium to run browser scraper tests",
)


async def test_browser_crawler_finds_meeting_page_from_fixture_site(tmp_path: Path) -> None:
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text(
        '<a href="/meetings.html">Find a meeting</a><a href="https://external.test/">Leave</a>',
        encoding="utf-8",
    )
    (site_dir / "meetings.html").write_text(
        """
        <table>
          <tr><th>Meeting</th><th>Day</th><th>Time</th><th>Address</th></tr>
          <tr><td>Monday Main</td><td>Monday</td><td>7:30 pm</td><td>10 Main Street</td></tr>
        </table>
        """,
        encoding="utf-8",
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(SimpleHTTPRequestHandler, directory=str(site_dir)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = Source(
            id="aa-fixture-site",
            fellowship="aa",
            name="Fixture Site",
            url=f"http://127.0.0.1:{server.server_port}/",
            source_type=SourceType.LOCAL_SERVICE_BODY,
            adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
            config={"timezone": "Europe/Dublin"},
            requires_browser=True,
        )
        result = await scrape_source(
            source,
            Settings(),
            crawl_settings=CrawlSettings(
                max_pages_per_source=3,
                max_depth=1,
                save_artifacts=True,
            ),
            artifact_dir=tmp_path / "artifacts",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result.scrape.status == "succeeded"
    assert result.scrape.pages_visited >= 2
    assert result.ingest.candidates[0].name == "Monday Main"
    assert result.scrape.artifact_dir is not None


async def test_browser_crawler_submits_search_form_from_source_context(tmp_path: Path) -> None:
    site_dir = tmp_path / "search-site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text(
        """
        <form action="/results.html">
          <input type="search" name="city">
        </form>
        """,
        encoding="utf-8",
    )
    (site_dir / "results.html").write_text(
        """
        <article class="meeting-card">
          <h3>Dublin Search Result</h3>
          <p>Tuesday 8:00 pm</p>
          <p class="address">22 River Road</p>
        </article>
        """,
        encoding="utf-8",
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(SimpleHTTPRequestHandler, directory=str(site_dir)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = Source(
            id="aa-search-site",
            fellowship="aa",
            name="Search Site",
            url=f"http://127.0.0.1:{server.server_port}/",
            region="Dublin",
            source_type=SourceType.LOCAL_SERVICE_BODY,
            adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
            config={"timezone": "Europe/Dublin"},
            requires_browser=True,
        )
        result = await scrape_source(
            source,
            Settings(),
            crawl_settings=CrawlSettings(
                max_pages_per_source=1,
                max_depth=0,
                save_artifacts=True,
            ),
            artifact_dir=tmp_path / "artifacts",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result.scrape.status == "succeeded"
    assert result.ingest.candidates[0].name == "Dublin Search Result"
    assert any(
        action.action == "heuristic_search_form" and action.status == "succeeded"
        for page in result.scrape.pages
        for action in page.actions
    )


async def test_browser_crawler_submits_group_search_form_from_source_metadata(
    tmp_path: Path,
) -> None:
    site_dir = tmp_path / "group-search-site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text(
        """
        <form id="group-search" action="/groups.html">
          <input type="search" name="q">
          <button type="submit">Find</button>
        </form>
        """,
        encoding="utf-8",
    )
    (site_dir / "groups.html").write_text(
        """
        <article class="meeting-card">
          <h3>Belize City Group</h3>
          <p>Wednesday 6:00 pm</p>
          <p class="address">114 Cemetery Road</p>
        </article>
        """,
        encoding="utf-8",
    )
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(SimpleHTTPRequestHandler, directory=str(site_dir)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = Source(
            id="aa-group-search-site",
            fellowship="aa",
            name="Group Search Site",
            url=f"http://127.0.0.1:{server.server_port}/",
            country="Belize",
            source_type=SourceType.LOCAL_SERVICE_BODY,
            adapter_type=AdapterType.PLAYWRIGHT_BROWSER,
            config={
                "timezone": "America/Belize",
                "metadata": {"address_text": "114 Cemetery Road Belize City Belize"},
            },
            requires_browser=True,
        )
        result = await scrape_source(
            source,
            Settings(),
            crawl_settings=CrawlSettings(
                max_pages_per_source=1,
                max_depth=0,
                save_artifacts=True,
            ),
            artifact_dir=tmp_path / "artifacts",
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result.scrape.status == "succeeded"
    assert result.ingest.candidates[0].name == "Belize City Group"
    assert any(
        action.action == "heuristic_search_form"
        and action.status == "succeeded"
        and action.value == "Belize City"
        for page in result.scrape.pages
        for action in page.actions
    )

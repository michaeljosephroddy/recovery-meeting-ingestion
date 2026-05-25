import httpx

from app.config import Settings
from app.sources.aa_world_services import AaWorldServicesDiscovery, aa_filter_queries_from_html
from app.sources.ca_world_services import (
    CA_WORLD_URL,
    CaWorldServicesDiscovery,
    is_valid_ca_local_source_url,
)
from app.sources.na_world_services import (
    NA_WORLD_URL,
    NaWorldServicesDiscovery,
    parse_location_index,
)
from app.sources.registry import SourceType

from .conftest import FIXTURES


def test_aa_world_fixture_produces_source_candidates_not_meetings() -> None:
    discovery = AaWorldServicesDiscovery(Settings())
    candidates = discovery.parse_html((FIXTURES / "aa_world.html").read_text())

    assert {candidate.fellowship for candidate in candidates} == {"aa"}
    assert len(candidates) == 4
    assert any(str(candidate.url) == "http://www.aadavis.org" for candidate in candidates)
    assert any(str(candidate.url) == "tel:9096284428" for candidate in candidates)
    assert any(candidate.country == "Ireland" for candidate in candidates)
    assert all(not hasattr(candidate, "occurrences") for candidate in candidates)


def test_aa_world_filter_options_produce_query_queue() -> None:
    html = """
    <select name="state">
      <option value="All">- Any -</option>
      <option value="CA">California</option>
    </select>
    <select name="state">
      <option value="ON">Ontario</option>
    </select>
    <select name="cc">
      <option value="IE">Ireland</option>
    </select>
    """

    assert aa_filter_queries_from_html(html) == [
        ("state", "CA"),
        ("state", "ON"),
        ("cc", "IE"),
    ]


async def test_aa_discover_walks_filter_query_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("state") == "CA":
            return httpx.Response(
                200,
                text="""
                <div class="view-locations-listing">
                  <div class="area-loc-item">
                    <h3>California AA</h3>
                    <address><span class="administrative-area">California</span></address>
                    <a href="https://local-aa.example/">Website</a>
                  </div>
                </div>
                """,
                request=request,
            )
        return httpx.Response(
            200,
            text="""
            <select name="state">
              <option value="All">- Any -</option>
              <option value="CA">California</option>
            </select>
            <select name="cc">
              <option value="IE">Ireland</option>
            </select>
            """,
            request=request,
        )

    discovery = AaWorldServicesDiscovery(
        Settings(default_rate_limit_seconds=0),
        transport=httpx.MockTransport(handler),
    )

    candidates = await discovery.discover(max_locations=1)

    assert any(str(candidate.url) == "https://local-aa.example/" for candidate in candidates)


def test_ca_world_fixture_produces_ca_source_candidates() -> None:
    discovery = CaWorldServicesDiscovery(Settings())
    candidates = discovery.parse_html((FIXTURES / "ca_world.html").read_text())

    assert {candidate.fellowship for candidate in candidates} == {"ca"}
    assert len(candidates) == 2
    assert {candidate.source_type for candidate in candidates} == {"world_service_listing"}


def test_ca_country_fixture_produces_local_source_candidates() -> None:
    discovery = CaWorldServicesDiscovery(Settings())
    candidates = discovery.parse_html_for_url(
        (FIXTURES / "ca_ireland.html").read_text(),
        "https://ca.org/meetings/ireland/",
    )

    assert len(candidates) == 1
    assert candidates[0].fellowship == "ca"
    assert str(candidates[0].url) == "https://www.caireland.live"
    assert candidates[0].country == "Ireland"


def test_ca_discovery_filters_ca_online_internal_and_direct_meeting_links() -> None:
    discovery = CaWorldServicesDiscovery(Settings())
    candidates = discovery.parse_html_for_url(
        """
        <a href="https://ca-online.org/">Online Service Area</a>
        <a href="https://ca-online.org/committees/">Committees</a>
        <a href="https://ca-online.org/osa-store/">Store</a>
        <a href="https://apps.apple.com/app/id6504262893">Mobile app</a>
        <a href="https://us02web.zoom.us/j/123456789">Zoom room</a>
        <a href="https://maps.app.goo.gl/example">Map</a>
        """,
        "https://ca.org/meetings/online-meetings/",
    )

    urls = {str(candidate.url).rstrip("/") for candidate in candidates}

    assert "https://ca-online.org" in urls
    assert "https://ca-online.org/committees" not in urls
    assert "https://ca-online.org/osa-store" not in urls
    assert "https://apps.apple.com/app/id6504262893" not in urls
    assert "https://us02web.zoom.us/j/123456789" not in urls
    assert "https://maps.app.goo.gl/example" not in urls


def test_ca_local_source_url_validation_rejects_non_site_targets() -> None:
    assert is_valid_ca_local_source_url("https://ca-online.org")
    assert is_valid_ca_local_source_url("https://www.caireland.live")
    assert not is_valid_ca_local_source_url("https://ca-online.org/events/")
    assert not is_valid_ca_local_source_url("https://play.google.com/store/apps/details?id=ca")
    assert not is_valid_ca_local_source_url("https://zoom.us/j/99813522508")
    assert not is_valid_ca_local_source_url("https://maps.app.goo.gl/eRtvZvAjvpJebo8LA")


async def test_ca_discover_stops_at_external_local_site_boundary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/meetings/":
            return httpx.Response(
                200,
                text='<a href="https://ca.org/meetings/online-meetings/">Online</a>',
                request=request,
            )
        if request.url.path == "/meetings/online-meetings/":
            return httpx.Response(
                302,
                headers={"location": "https://local-ca.example/"},
                request=request,
            )
        if request.url.host == "local-ca.example":
            return httpx.Response(
                200,
                text="""
                <a href="https://local-ca.example/events/">Events</a>
                <a href="https://apps.apple.com/app/example">App Store</a>
                """,
                request=request,
            )
        return httpx.Response(404, request=request)

    discovery = CaWorldServicesDiscovery(
        Settings(default_rate_limit_seconds=0),
        transport=httpx.MockTransport(handler),
    )

    candidates = await discovery.discover(max_locations=2)

    urls = {str(candidate.url) for candidate in candidates}
    assert "https://local-ca.example/" in urls
    assert "https://local-ca.example/events/" not in urls
    assert "https://apps.apple.com/app/example" not in urls


async def test_ca_discover_preserves_listing_region_after_external_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/meetings/":
            return httpx.Response(
                200,
                text='<a href="https://ca.org/meetings/united-states/arizona/">Arizona</a>',
                request=request,
            )
        if request.url.path == "/meetings/united-states/arizona/":
            return httpx.Response(
                302,
                headers={"location": "https://caarizona.example/"},
                request=request,
            )
        if request.url.host == "caarizona.example":
            return httpx.Response(200, text="<html></html>", request=request)
        return httpx.Response(404, request=request)

    discovery = CaWorldServicesDiscovery(
        Settings(default_rate_limit_seconds=0),
        transport=httpx.MockTransport(handler),
    )

    candidates = await discovery.discover(max_locations=2)
    local = next(candidate for candidate in candidates if str(candidate.url) == "https://caarizona.example/")

    assert local.country == "United States"
    assert local.region == "Arizona"


async def test_ca_discover_follows_nested_world_listing_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/meetings/":
            return httpx.Response(
                200,
                text="""
                <a href="https://ca.org/meetings/united-states/">United States</a>
                """,
                request=request,
            )
        if request.url.path == "/meetings/united-states/":
            return httpx.Response(
                200,
                text="""
                <a href="https://ca.org/meetings/united-states/california/">California</a>
                """,
                request=request,
            )
        if request.url.path == "/meetings/united-states/california/":
            return httpx.Response(
                200,
                text="""
                <a href="https://example-ca.org/meetings">Example CA Area</a>
                """,
                request=request,
            )
        return httpx.Response(404, request=request)

    discovery = CaWorldServicesDiscovery(
        Settings(default_rate_limit_seconds=0),
        transport=httpx.MockTransport(handler),
    )

    candidates = await discovery.discover(max_locations=3)

    assert any(str(candidate.url) == "https://example-ca.org/meetings" for candidate in candidates)
    local = next(candidate for candidate in candidates if str(candidate.url).startswith("https://example-ca.org"))
    assert local.source_type == SourceType.LOCAL_SERVICE_BODY
    assert local.country == "United States"
    assert local.region == "California"


async def test_na_discover_fetches_locator_page_before_ajax_requests() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/meetingsearch/find-na/":
            return httpx.Response(200, text="<html>locator</html>", request=request)
        if request.method == "POST" and request.url.path.endswith("/ajax.php"):
            form = dict(request.url.params)
            content = request.content.decode()
            if "action=search" in content:
                return httpx.Response(
                    200,
                    json={
                        "status": "success",
                        "data": [],
                        "ll_us": [{"state": "New York"}],
                        "ll_ca": [],
                        "ll_intl": [],
                    },
                    request=request,
                )
            if "action=listings" in content:
                return httpx.Response(
                    200,
                    json={
                        "status": "success",
                        "data": [
                            {
                                "description": "Heart of New York Area",
                                "website": "https://nny-na.org/find-a-meeting/",
                                "country": "United States",
                                "state": "New York",
                                "type": "Area",
                            }
                        ],
                    },
                    request=request,
                )
            raise AssertionError(f"unexpected form payload: {form} {content}")
        return httpx.Response(404, request=request)

    discovery = NaWorldServicesDiscovery(
        Settings(default_rate_limit_seconds=0),
        transport=httpx.MockTransport(handler),
    )

    candidates = await discovery.discover(max_locations=1)

    assert [method for method, _path in requests] == ["GET", "POST", "POST"]
    assert len(candidates) == 1
    assert str(candidates[0].url) == "https://nny-na.org/find-a-meeting/"
    assert candidates[0].country == "United States"
    assert candidates[0].region == "New York"


def test_na_world_fixture_produces_na_source_candidates() -> None:
    discovery = NaWorldServicesDiscovery(Settings())
    payload = (FIXTURES / "na_locator.json").read_text()
    candidates = discovery.parse_html(payload)

    assert {candidate.fellowship for candidate in candidates} == {"na"}
    assert len(candidates) == 2
    assert str(candidates[0].url) == "https://www.na-ireland.org/na-meetings/east/"
    assert str(candidates[1].url) == "tel:+18334366166"
    assert candidates[1].source_type == "phone"


def test_na_locator_payload_produces_seed_locations() -> None:
    locations = parse_location_index((FIXTURES / "na_locator.json").read_text())

    assert locations == [
        {"country": "United States", "state": "New York"},
        {"country": "Canada", "state": "Ontario"},
        {"country": "Ireland", "state": ""},
    ]


def test_world_service_default_urls_match_official_pages() -> None:
    assert NA_WORLD_URL == "https://na.org/meetingsearch/find-na/"
    assert CA_WORLD_URL == "https://ca.org/meetings/"

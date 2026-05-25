from app.adapters.base import RawMeeting
from app.adapters.bmlt import BmltAdapter
from app.config import Settings
from app.sources.registry import AdapterType, Source, SourceType, timezone_for_country_region

_DIRECT_BMLT_ENDPOINTS = {
    "na-07fdcb08f177": (
        "https://tomato.bmltenabled.org/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services[]=16&recursive=1"
    ),
    "na-41b6e1cb9842": (
        "https://pszfna.org/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services[]=42&recursive=1"
    ),
    "na-0e14cccfb90e": (
        "https://bmlt.wszf.org/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services[]=1150&recursive=1"
    ),
    "na-6ae02f8589f4": (
        "https://meetings.naworks.org/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services[]=9&recursive=1"
    ),
    "na-7b9dd88bb350": (
        "https://bmlt.wszf.org/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services[]=1152&recursive=1"
    ),
    "na-87c9f3b0caef": (
        "https://aggregator.bmltenabled.org/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services[]=1565&recursive=1"
    ),
    "na-94eed0942491": (
        "https://texasoklahomana.org/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services[]=1018&recursive=1"
    ),
    "na-a78c156fa126": (
        "https://metrorichna.org/BMLT/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services[]=38&recursive=1"
    ),
    "na-b2575093eb9d": (
        "https://na-hawaii.org/bmltmain/client_interface/json/"
        "?switcher=GetSearchResults&services[]=1&recursive=1"
    ),
    "na-f89bb33e4f09": (
        "https://tomato.bmltenabled.org/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services[]=162"
    ),
    "na-ff485154ee5f": (
        "https://aggregator.bmltenabled.org/main_server/client_interface/json/"
        "?switcher=GetSearchResults&services[]=1955&recursive=1"
    ),
}


async def fetch_direct_bmlt_records(
    source: Source,
    settings: Settings,
) -> tuple[Source, list[RawMeeting]] | None:
    endpoint = _DIRECT_BMLT_ENDPOINTS.get(source.id)
    if endpoint is None:
        return None
    existing_scrape = source.config.get("scrape")
    scrape_config = existing_scrape if isinstance(existing_scrape, dict) else {}
    timezone = timezone_for_country_region(source.country, source.region)
    adapter_source = source.model_copy(
        update={
            "source_type": SourceType.MEETING_FEED,
            "adapter_type": AdapterType.BMLT,
            "requires_browser": False,
            "config": {
                **source.config,
                **({"timezone": timezone} if timezone else {}),
                "bmlt_search_endpoint": endpoint,
                "scrape": {
                    **scrape_config,
                    "fallback": "direct_bmlt",
                    "discovered_endpoint": endpoint,
                },
            },
        }
    )
    return adapter_source, await BmltAdapter(adapter_source, settings.user_agent).fetch()

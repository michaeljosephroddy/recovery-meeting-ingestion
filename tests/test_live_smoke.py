import os

import pytest

from app.adapters.bmlt import BmltAdapter
from app.adapters.meeting_guide import MeetingGuideAdapter
from app.config import Settings
from app.sources.aa_feed_registry import build_meeting_guide_source
from app.sources.registry import AdapterType, Source, SourceType

pytestmark = pytest.mark.live


async def test_live_meeting_guide_feed_smoke() -> None:
    feed_url = os.environ.get("LIVE_MEETING_GUIDE_URL")
    if os.environ.get("RUN_LIVE_TESTS") != "1" or not feed_url:
        pytest.skip("set RUN_LIVE_TESTS=1 and LIVE_MEETING_GUIDE_URL to run")

    settings = Settings()
    source = build_meeting_guide_source("live-aa", feed_url)
    records = await MeetingGuideAdapter(source, settings.user_agent).fetch()

    assert records


async def test_live_bmlt_feed_smoke() -> None:
    root_url = os.environ.get("LIVE_BMLT_ROOT_URL")
    if os.environ.get("RUN_LIVE_TESTS") != "1" or not root_url:
        pytest.skip("set RUN_LIVE_TESTS=1 and LIVE_BMLT_ROOT_URL to run")

    settings = Settings()
    source = Source(
        id="live-bmlt",
        fellowship="na",
        name="Live BMLT",
        url=root_url,
        source_type=SourceType.MEETING_FEED,
        adapter_type=AdapterType.BMLT,
    )
    records = await BmltAdapter(source, settings.user_agent).fetch()

    assert records


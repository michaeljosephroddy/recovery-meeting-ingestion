from app.sources.registry import AdapterType, Source, SourceType


def build_meeting_guide_source(source_id: str, feed_url: str, country: str | None = None) -> Source:
    return Source(
        id=source_id,
        fellowship="aa",
        name=source_id,
        url=feed_url,
        country=country,
        source_type=SourceType.MEETING_FEED,
        adapter_type=AdapterType.MEETING_GUIDE,
    )

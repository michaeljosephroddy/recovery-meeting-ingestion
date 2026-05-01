from typing import Any

DAY_FIELDS = {"day", "weekday"}
TIME_FIELDS = {"time", "start_time", "start"}
NAME_FIELDS = {"name", "meeting_name", "group"}
LOCATION_FIELDS = {"address", "address_line1", "city", "venue_name", "location"}
ONLINE_FIELDS = {"online_url", "conference_url", "url", "phone_join_info"}


def confidence_for_payload(
    payload: dict[str, Any],
    *,
    method: str,
    page_score: float = 0.0,
    repeated_structure: bool = False,
    table_headers: bool = False,
) -> tuple[float, list[str]]:
    signals: list[str] = []
    score = 0.05
    if _has_any(payload, DAY_FIELDS):
        score += 0.18
        signals.append("day")
    if _has_any(payload, TIME_FIELDS):
        score += 0.20
        signals.append("time")
    if _has_any(payload, NAME_FIELDS):
        score += 0.12
        signals.append("name")
    if _has_any(payload, LOCATION_FIELDS):
        score += 0.14
        signals.append("location")
    if _has_any(payload, ONLINE_FIELDS):
        score += 0.12
        signals.append("online")
    if repeated_structure:
        score += 0.10
        signals.append("repeated_structure")
    if table_headers:
        score += 0.10
        signals.append("table_headers")
    if page_score >= 0.5:
        score += 0.07
        signals.append("meeting_page")

    if method == "heuristic_text_block":
        score -= 0.14
        signals.append("text_fallback")
    if not _has_any(payload, DAY_FIELDS):
        score -= 0.12
        signals.append("missing_day")
    if not _has_any(payload, TIME_FIELDS):
        score -= 0.14
        signals.append("missing_time")
    if not (_has_any(payload, LOCATION_FIELDS) or _has_any(payload, ONLINE_FIELDS)):
        score -= 0.10
        signals.append("missing_location")

    return max(0.0, min(1.0, round(score, 2))), signals


def review_code_for_confidence(confidence: float) -> str | None:
    if confidence < 0.45:
        return "scrape_very_low_confidence"
    if confidence < 0.75:
        return "scrape_low_confidence"
    return None


def _has_any(payload: dict[str, Any], fields: set[str]) -> bool:
    return any(str(payload.get(field) or "").strip() for field in fields)


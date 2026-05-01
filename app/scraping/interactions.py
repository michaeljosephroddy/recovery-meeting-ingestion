from contextlib import suppress
from typing import Any

from app.adapters.base import AdapterPayloadError
from app.scraping.models import BrowserActionTrace, CrawlSettings
from app.sources.registry import Source

MEETING_BUTTON_TEXT = (
    "meetings",
    "meeting list",
    "find a meeting",
    "search",
    "list",
    "list view",
    "load more",
    "more meetings",
    "next",
    "show more",
)


async def perform_configured_actions(page: Any, actions: object) -> list[BrowserActionTrace]:
    if actions in (None, ""):
        return []
    if not isinstance(actions, list):
        raise AdapterPayloadError("browser actions must be a list")

    traces: list[BrowserActionTrace] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise AdapterPayloadError(f"browser action {index} must be an object")
        trace = await _perform_configured_action(page, action, index)
        traces.append(trace)
    return traces


async def perform_heuristic_interactions(
    page: Any,
    source: Source,
    settings: CrawlSettings,
) -> list[BrowserActionTrace]:
    traces: list[BrowserActionTrace] = []
    for selector in _button_selectors():
        if len(traces) >= settings.max_actions_per_page:
            break
        trace = await _try_click(
            page,
            selector,
            action="heuristic_click",
            timeout_ms=settings.action_timeout_ms,
        )
        if trace is not None:
            traces.append(trace)

    if len(traces) < settings.max_actions_per_page:
        form_trace = await _try_submit_search_form(page, source)
        if form_trace is not None:
            traces.append(form_trace)
    return traces


async def _perform_configured_action(
    page: Any,
    action: dict[str, Any],
    index: int,
) -> BrowserActionTrace:
    action_type = str(action.get("type") or action.get("action") or "").strip()
    if not action_type:
        raise AdapterPayloadError(f"browser action {index} is missing type")
    selector = action.get("selector")
    try:
        if action_type == "wait_for_selector":
            required_selector = _required_string(action, "selector", index)
            await page.wait_for_selector(required_selector)
            trace_selector = required_selector
        elif action_type == "wait_for_timeout":
            await page.wait_for_timeout(_required_int(action, "milliseconds", index))
            trace_selector = None
        elif action_type == "wait_for_load_state":
            state = str(action.get("state") or "networkidle")
            await page.wait_for_load_state(state)
            trace_selector = None
        elif action_type == "fill":
            required_selector = _required_string(action, "selector", index)
            value = _required_string(action, "value", index)
            await page.fill(required_selector, value)
            trace_selector = required_selector
        elif action_type == "click":
            required_selector = _required_string(action, "selector", index)
            await page.click(required_selector)
            trace_selector = required_selector
        elif action_type == "press":
            required_selector = _required_string(action, "selector", index)
            await page.press(required_selector, _required_string(action, "key", index))
            trace_selector = required_selector
        elif action_type == "select_option":
            required_selector = _required_string(action, "selector", index)
            await page.select_option(required_selector, _select_option_value(action, index))
            trace_selector = required_selector
        elif action_type == "check":
            required_selector = _required_string(action, "selector", index)
            await page.check(required_selector)
            trace_selector = required_selector
        elif action_type == "uncheck":
            required_selector = _required_string(action, "selector", index)
            await page.uncheck(required_selector)
            trace_selector = required_selector
        else:
            raise AdapterPayloadError(f"unsupported browser action type: {action_type}")

        wait_for = action.get("wait_for_selector") or action.get("wait_for")
        if wait_for:
            await page.wait_for_selector(str(wait_for))
        load_state = action.get("wait_for_load_state")
        if load_state:
            await page.wait_for_load_state(str(load_state))
        return BrowserActionTrace(
            action=action_type,
            selector=str(trace_selector) if trace_selector else None,
            value=str(action.get("value")) if action.get("value") is not None else None,
        )
    except Exception as exc:
        if isinstance(exc, AdapterPayloadError):
            raise
        return BrowserActionTrace(
            action=action_type,
            selector=str(selector) if selector else None,
            status="failed",
            message=str(exc),
        )


async def _try_click(
    page: Any,
    selector: str,
    *,
    action: str,
    timeout_ms: int,
) -> BrowserActionTrace | None:
    try:
        locator = page.locator(selector).first
        if callable(locator):
            locator = locator()
        if await locator.count() == 0:
            return None
        if not await locator.is_visible(timeout=250):
            return None
        action_timeout = min(timeout_ms, 1_500)
        await locator.click(timeout=action_timeout)
        with suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=action_timeout)
        return BrowserActionTrace(action=action, selector=selector)
    except Exception as exc:
        return BrowserActionTrace(
            action=action,
            selector=selector,
            status="failed",
            message=str(exc),
        )


async def _try_submit_search_form(page: Any, source: Source) -> BrowserActionTrace | None:
    seed = str(source.config.get("city") or source.region or "").strip()
    if not seed:
        return BrowserActionTrace(
            action="heuristic_search_form",
            status="skipped",
            message="needs_search_seed",
        )
    selectors = (
        "form input[name*='city' i]",
        "form input[name*='location' i]",
        "form input[name*='postcode' i]",
        "form input[name*='zip' i]",
        "form[aria-label*='meeting' i] input[type='search']",
        "form[id*='meeting' i] input[type='search']",
        "form[class*='meeting' i] input[type='search']",
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if callable(locator):
                locator = locator()
            if await locator.count() == 0:
                continue
            await locator.fill(seed, timeout=1_500)
            await locator.press("Enter", timeout=1_500)
            with suppress(Exception):
                await page.wait_for_load_state("networkidle", timeout=1_500)
            return BrowserActionTrace(
                action="heuristic_search_form",
                selector=selector,
                value=seed,
            )
        except Exception as exc:
            return BrowserActionTrace(
                action="heuristic_search_form",
                selector=selector,
                value=seed,
                status="failed",
                message=str(exc),
            )
    return None


def configured_actions_from_source(source: Source) -> object:
    browser_config = browser_config_from_source(source)
    return browser_config.get("actions", source.config.get("browser_actions"))


def browser_config_from_source(source: Source) -> dict[str, Any]:
    browser_config = source.config.get("browser")
    if browser_config is None:
        return source.config
    if not isinstance(browser_config, dict):
        raise AdapterPayloadError("source config browser must be an object")
    return {**source.config, **browser_config}


def _button_selectors() -> list[str]:
    selectors = [
        "[aria-expanded='false']",
        "button[aria-controls]",
    ]
    for text in MEETING_BUTTON_TEXT:
        selectors.extend(
            [
                f'button:has-text("{text}")',
                f'[role="button"]:has-text("{text}")',
            ]
        )
    return selectors


def _required_string(action: dict[str, Any], key: str, index: int) -> str:
    value = action.get(key)
    if value is None or str(value).strip() == "":
        raise AdapterPayloadError(f"browser action {index} is missing {key}")
    return str(value)


def _required_int(action: dict[str, Any], key: str, index: int) -> int:
    value = action.get(key)
    if value is None:
        raise AdapterPayloadError(f"browser action {index} is missing {key}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AdapterPayloadError(f"browser action {index} {key} must be an integer") from exc


def _select_option_value(action: dict[str, Any], index: int) -> object:
    if "options" in action:
        return action["options"]
    if "value" in action:
        return str(action["value"])
    if "label" in action:
        return {"label": str(action["label"])}
    if "index" in action:
        return {"index": _required_int(action, "index", index)}
    raise AdapterPayloadError(f"browser action {index} is missing value, label, index, or options")

from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from app.adapters.base import AdapterFetchError, AdapterPayloadError


async def fetch_json_array(
    url: str,
    *,
    user_agent: str,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_seconds: float = 20.0,
) -> list[dict[str, Any]]:
    try:
        response = await _fetch_response(
            url,
            user_agent=user_agent,
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        raise AdapterFetchError(f"failed to fetch {url}: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise AdapterPayloadError(f"source did not return valid JSON: {url}") from exc

    if not isinstance(payload, list):
        raise AdapterPayloadError(f"source JSON payload must be an array: {url}")
    if not all(isinstance(item, dict) for item in payload):
        raise AdapterPayloadError(f"source JSON array must contain objects: {url}")
    return payload


async def _fetch_response(
    url: str,
    *,
    user_agent: str,
    transport: httpx.AsyncBaseTransport | None,
    timeout_seconds: float,
) -> httpx.Response:
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=timeout_seconds,
        follow_redirects=True,
        transport=transport,
    ) as client:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception(_is_retryable_exception),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.25, max=2),
            reraise=True,
        ):
            with attempt:
                response = await client.get(url)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if _is_retryable_status(exc.response.status_code):
                        raise
                    raise AdapterFetchError(
                        f"non-retryable HTTP {exc.response.status_code} from {url}"
                    ) from exc
                return response
    raise AdapterFetchError(f"failed to fetch {url}")


def _is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return _is_retryable_status(exc.response.status_code)
    return False


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 429} or 500 <= status_code <= 599


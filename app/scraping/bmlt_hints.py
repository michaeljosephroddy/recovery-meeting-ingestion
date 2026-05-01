import json
import re
from urllib.parse import parse_qsl, urlencode

BMLT_ROOT_RE = re.compile(r'"root_server"\s*:\s*"(?P<url>[^"]+)"')
CUSTOM_QUERY_RE = re.compile(r'"custom_query"\s*:\s*"(?P<query>[^"]*)"')
RECURSE_RE = re.compile(r'"recurse_service_bodies"\s*:\s*(?P<value>true|false|"[^"]*")')
SERVICE_BODY_RE = re.compile(r'"service_body"\s*:\s*\[(?P<body>[^\]]*)\]')
SERVICE_ID_RE = re.compile(r'"(?P<id>\d+)"')


def bmlt_endpoint_from_html(html: str) -> str | None:
    root_match = BMLT_ROOT_RE.search(html)
    if root_match is None:
        return None
    root_url = _decode_js_string(root_match.group("url")).rstrip("/")
    params: list[tuple[str, str]] = [("switcher", "GetSearchResults")]
    custom_query_params = _custom_query_params(html)
    if custom_query_params:
        params.extend(custom_query_params)
    else:
        service_ids = _service_body_ids(html)
        params.extend(("services[]", service_id) for service_id in service_ids)
    if _recurse_service_bodies(html):
        params.append(("recursive", "1"))
    return f"{root_url}/client_interface/json/?{urlencode(params)}"


def _custom_query_params(html: str) -> list[tuple[str, str]]:
    match = CUSTOM_QUERY_RE.search(html)
    if match is None:
        return []
    query = _decode_js_string(match.group("query"))
    return [(key, value) for key, value in parse_qsl(query, keep_blank_values=False)]


def _recurse_service_bodies(html: str) -> bool:
    match = RECURSE_RE.search(html)
    if match is None:
        return False
    value = match.group("value").strip('"').lower()
    return value in {"1", "true", "yes", "on"}


def _service_body_ids(html: str) -> list[str]:
    match = SERVICE_BODY_RE.search(html)
    if match is None:
        return []
    return [service_id.group("id") for service_id in SERVICE_ID_RE.finditer(match.group("body"))]


def _decode_js_string(value: str) -> str:
    try:
        decoded = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value.replace("\\/", "/")
    return str(decoded)

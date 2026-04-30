from typing import Any

from selectolax.parser import HTMLParser, Node

from app.adapters.base import AdapterPayloadError


def configured_selectors(config: dict[str, Any]) -> dict[str, str]:
    selectors = config.get("selectors")
    if not isinstance(selectors, dict):
        raise AdapterPayloadError("source config must contain selectors")
    if not isinstance(selectors.get("row"), str):
        raise AdapterPayloadError("source config selectors must include row")
    return {str(key): str(value) for key, value in selectors.items() if value}


def extract_records_from_html(html: str, selectors: dict[str, str]) -> list[dict[str, Any]]:
    parser = HTMLParser(html)
    records: list[dict[str, Any]] = []
    rows = parser.css(selectors["row"])
    for index, row in enumerate(rows):
        payload: dict[str, Any] = {"row_index": index}
        for field, selector in selectors.items():
            if field == "row":
                continue
            payload[field] = _text_or_attr(row, selector)
        records.append(payload)
    return records


def _text_or_attr(row: Node, selector: str) -> str | None:
    attr_name: str | None = None
    css_selector = selector
    if "::attr(" in selector and selector.endswith(")"):
        css_selector, attr_part = selector.split("::attr(", 1)
        attr_name = attr_part[:-1]
    node = row.css_first(css_selector)
    if node is None:
        return None
    if attr_name:
        return node.attributes.get(attr_name)
    text = " ".join(node.text(separator=" ", strip=True).split())
    return text or None


from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag
from soupsieve import match as selector_matches

from app.adapters.base import AdapterPayloadError


def configured_selectors(config: dict[str, Any]) -> dict[str, str]:
    selectors = config.get("selectors")
    if not isinstance(selectors, dict):
        raise AdapterPayloadError("source config must contain selectors")
    if not isinstance(selectors.get("row"), str):
        raise AdapterPayloadError("source config selectors must include row")
    return {str(key): str(value) for key, value in selectors.items() if value}


def extract_records_from_html(html: str, selectors: dict[str, str]) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[dict[str, Any]] = []
    rows = soup.select(selectors["row"])
    for index, row in enumerate(rows):
        payload: dict[str, Any] = {"row_index": index}
        for field, selector in selectors.items():
            if field == "row":
                continue
            payload[field] = _text_or_attr(row, selector)
        records.append(payload)
    return records


def _text_or_attr(row: Tag, selector: str) -> str | None:
    attr_name: str | None = None
    css_selector = selector
    if "::attr(" in selector and selector.endswith(")"):
        css_selector, attr_part = selector.split("::attr(", 1)
        attr_name = attr_part[:-1]
    node = row if selector_matches(css_selector, row) else row.select_one(css_selector)
    if node is None:
        return None
    if attr_name:
        value = node.get(attr_name)
        if isinstance(value, list):
            return " ".join(str(item) for item in value).strip() or None
        return str(value).strip() if value is not None else None
    text = " ".join(node.get_text(separator=" ", strip=True).split())
    return text or None

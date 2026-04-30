from typing import Any

import httpx

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.adapters.static_html import StaticHtmlAdapter
from app.normalize.canonical import CanonicalMeetingCandidate
from app.sources.registry import Source


class FormHttpAdapter:
    def __init__(
        self,
        source: Source,
        user_agent: str = "SoberSpaceRecoveryMeetingIngestion/0.1",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.source = source
        self.user_agent = user_agent
        self.transport = transport

    async def fetch(self) -> list[RawMeeting]:
        request_config = self.source.config.get("request")
        if not isinstance(request_config, dict):
            raise AdapterPayloadError("form_http source config must include request")
        method = str(request_config.get("method") or "GET").upper()
        url = str(request_config.get("url") or self.source.url)
        params = _dict_or_none(request_config.get("params"))
        data = _dict_or_none(request_config.get("data"))
        json_body = _dict_or_none(request_config.get("json"))
        async with httpx.AsyncClient(
            headers={"User-Agent": self.user_agent},
            timeout=20.0,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            response = await client.request(
                method,
                url,
                params=params,
                data=data,
                json=json_body,
            )
            response.raise_for_status()
        return self.raw_records_from_response(response)

    def raw_records_from_response(self, response: httpx.Response) -> list[RawMeeting]:
        result_type = str(self.source.config.get("result_type") or "html")
        if result_type == "json":
            payload = response.json()
            if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
                raise AdapterPayloadError("form_http JSON result must be an array of objects")
            html = _json_payloads_to_html(payload)
            return StaticHtmlAdapter(self.source).raw_records_from_html(html)
        if result_type == "html":
            return self.raw_records_from_html(response.text)
        raise AdapterPayloadError(f"unsupported form_http result_type: {result_type}")

    def raw_records_from_html(self, html: str) -> list[RawMeeting]:
        # Reuse the configured static HTML parser and keep this adapter focused on form transport.
        return StaticHtmlAdapter(self.source).raw_records_from_html(html)

    def normalize(self, raw: RawMeeting) -> CanonicalMeetingCandidate:
        return StaticHtmlAdapter(self.source).normalize(raw)


def _dict_or_none(value: object) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _json_payloads_to_html(payloads: list[dict[str, Any]]) -> str:
    rows = []
    for payload in payloads:
        cells = "".join(f'<span class="{key}">{value}</span>' for key, value in payload.items())
        rows.append(f'<div class="meeting">{cells}</div>')
    return "\n".join(rows)

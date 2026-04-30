import hashlib

import httpx

from app.adapters.base import AdapterPayloadError, RawMeeting
from app.normalize.canonical import CanonicalMeetingCandidate
from app.sources.registry import Source


class PdfAdapter:
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
        async with httpx.AsyncClient(
            headers={"User-Agent": self.user_agent},
            timeout=30.0,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            response = await client.get(self.source.url)
            response.raise_for_status()
        text = extract_pdf_text(response.content)
        payload = {"text": text, "review_required": True}
        return [
            RawMeeting(
                source_id=self.source.id,
                source_record_id=hashlib.sha1(
                    response.content,
                    usedforsecurity=False,
                ).hexdigest()[:16],
                source_url=self.source.url,
                payload=payload,
                content_hash=hashlib.sha256(response.content).hexdigest(),
            )
        ]

    def normalize(self, raw: RawMeeting) -> CanonicalMeetingCandidate:
        raise AdapterPayloadError(
            "PDF sources require source-specific parsing before canonical normalization"
        )


def extract_pdf_text(content: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError as exc:
        raise AdapterPayloadError(
            "pypdf optional dependency is required for PDF extraction"
        ) from exc
    import io

    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)

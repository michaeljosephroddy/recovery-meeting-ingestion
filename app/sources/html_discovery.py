from selectolax.parser import HTMLParser

from app.sources.registry import SourceCandidate, SourceType, absolute_url


def discover_source_links(
    html: str,
    *,
    base_url: str,
    fellowship: str,
    default_country: str | None = None,
) -> list[SourceCandidate]:
    parser = HTMLParser(html)
    candidates: list[SourceCandidate] = []
    seen: set[str] = set()
    for link in parser.css("a"):
        href = link.attributes.get("href")
        label = " ".join(link.text(separator=" ", strip=True).split())
        if not href or not label:
            continue
        if href.startswith(("mailto:", "tel:", "#")):
            continue
        url = absolute_url(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        candidates.append(
            SourceCandidate(
                fellowship=fellowship,  # type: ignore[arg-type]
                url=url,
                label=label,
                country=default_country,
                source_type=SourceType.LOCAL_SERVICE_BODY,
            )
        )
    return candidates


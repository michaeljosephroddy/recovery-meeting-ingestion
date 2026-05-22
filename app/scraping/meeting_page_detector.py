import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.scraping.meeting_vocabulary import (
    DAY_RE,
    MEETING_TEXT_TERMS,
    MEETING_URL_TERMS,
    STRONG_MEETING_PATH_SUFFIXES,
)

NEGATIVE_TERMS = {
    "donate",
    "donation",
    "news",
    "blog",
    "login",
    "signup",
    "privacy",
    "contact",
    "shop",
    "event",
    "events",
    "download",
    "downloads",
    "form",
    "forms",
    "register",
    "registration",
    "service meeting",
    "service-meeting",
    "service-meetings",
    "start-a-meeting",
    "update-register",
}
TIME_RE = re.compile(
    r"\b(?:(?:\d{1,2}(?::|\.|;)?\d{2}|\d{1,2})\s*(?:am|pm|a\.m\.|p\.m\.)|"
    r"kl\.?\s*(?:[01]?\d|2[0-3])(?:(?::|\.)[0-5]\d)?"
    r"(?:\s*(?:to|-|–|—)\s*(?:[01]?\d|2[0-3])(?:(?::|\.)[0-5]\d)?)?|"
    r"(?:[01]?\d|2[0-3]):[0-5]\d"
    r"(?:\s*(?:to|-|–|—)\s*(?:[01]?\d|2[0-3]):[0-5]\d)?|"
    r"12\s*noon|midnight)"
    r"(?=\W|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PageScore:
    score: float
    signals: list[str] = field(default_factory=list)
    negative_signals: list[str] = field(default_factory=list)


def score_link(url: str, text: str = "") -> PageScore:
    parsed = urlparse(url)
    value = f"{parsed.path} {parsed.query} {text}".lower()
    score = 0.0
    signals: list[str] = []
    negative: list[str] = []
    if _is_strong_public_meeting_directory(parsed.path, parsed.query, text):
        score += 0.45
        signals.append("strong_public_meeting_directory")
    for term in MEETING_URL_TERMS:
        if term in value:
            score += 0.25
            signals.append(f"url_or_text:{term}")
    for term in MEETING_TEXT_TERMS:
        if term in value:
            score += 0.18
            signals.append(f"text:{term}")
    for term in NEGATIVE_TERMS:
        if term in value:
            score -= 0.35
            negative.append(term)
    return PageScore(
        score=max(0.0, min(1.0, round(score, 2))),
        signals=signals,
        negative_signals=negative,
    )


def _is_strong_public_meeting_directory(path: str, query: str, text: str) -> bool:
    lowered_path = path.rstrip("/").lower()
    lowered_query = query.lower()
    lowered_text = text.lower()
    if lowered_path.endswith(
        tuple(STRONG_MEETING_PATH_SUFFIXES)
    ):
        return True
    if "tsml-attendance_option=" in lowered_query or "tsml-type=" in lowered_query:
        return True
    return any(
        term in lowered_text
        for term in (
            "find a meeting",
            "find an online meeting",
            "find a face-to-face meeting",
            "meeting schedule",
            "view all meetings",
        )
    )


def score_html(url: str, html: str) -> PageScore:
    soup = BeautifulSoup(html, "html.parser")
    text = " ".join(soup.get_text(" ", strip=True).split()).lower()
    score = score_link(url, _page_title_and_headings(soup))
    value = score.score
    signals = list(score.signals)
    negative = list(score.negative_signals)

    if DAY_RE.search(text) and TIME_RE.search(text):
        value += 0.26
        signals.append("day_and_time_text")
    if _has_meeting_form(soup):
        value += 0.24
        signals.append("meeting_form")
    if _has_meeting_table(soup):
        value += 0.24
        signals.append("meeting_table")
    for term in MEETING_TEXT_TERMS:
        if term in text:
            value += 0.06
            signals.append(f"body:{term}")
    for term in NEGATIVE_TERMS:
        if term in text:
            value -= 0.04
            negative.append(f"body:{term}")

    return PageScore(
        score=max(0.0, min(1.0, round(value, 2))),
        signals=_dedupe(signals),
        negative_signals=_dedupe(negative),
    )


def _page_title_and_headings(soup: BeautifulSoup) -> str:
    parts: list[str] = []
    if soup.title and soup.title.string:
        parts.append(soup.title.string)
    for heading in soup.select("h1, h2, h3"):
        parts.append(heading.get_text(" ", strip=True))
    return " ".join(parts)


def _has_meeting_form(soup: BeautifulSoup) -> bool:
    for form in soup.select("form"):
        value = " ".join(form.get_text(" ", strip=True).lower().split())
        attrs = " ".join(
            str(attr_value).lower()
            for tag in form.select("input, select, button")
            for attr_value in tag.attrs.values()
        )
        if "meeting" in value or "meeting" in attrs or "day" in attrs or "city" in attrs:
            return True
    return False


def _has_meeting_table(soup: BeautifulSoup) -> bool:
    table_terms = {"day", "time", "meeting", "location", "address", "city", "group", "type"}
    for table in soup.select("table"):
        headers = " ".join(
            cell.get_text(" ", strip=True).lower() for cell in table.select("th")
        )
        if sum(1 for term in table_terms if term in headers) >= 2:
            return True
    return False


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))

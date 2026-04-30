from app.sources.registry import (
    SourceCandidate,
    normalize_source_url,
    source_from_candidate,
    source_id_for_candidate,
)


def test_normalize_source_url_is_stable() -> None:
    assert (
        normalize_source_url("HTTPS://Example.ORG/path/?b=2&a=1#fragment")
        == "https://example.org/path?a=1&b=2"
    )
    assert normalize_source_url("https://example.org/path/") == "https://example.org/path"


def test_source_from_candidate_has_stable_id_and_normalized_url() -> None:
    candidate = SourceCandidate(
        fellowship="aa",
        label="Example Intergroup",
        url="https://Example.org/meetings/?b=2&a=1",
        country="US",
    )
    source = source_from_candidate(candidate)

    assert source.id == source_id_for_candidate(candidate)
    assert source.id.startswith("aa-")
    assert source.name == "Example Intergroup"
    assert source.normalized_url == "https://example.org/meetings?a=1&b=2"


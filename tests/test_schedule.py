import pytest

from app.normalize.schedule import normalize_days


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Lune", [1]),
        ("Marte", [2]),
        ("Miercole", [3]),
        ("Jueve", [4]),
        ("Vierne", [5]),
    ],
)
def test_normalize_days_accepts_truncated_spanish_weekdays(value: str, expected: list[int]) -> None:
    assert normalize_days(value) == expected


def test_normalize_days_returns_empty_for_unknown_text() -> None:
    assert normalize_days("not a weekday") == []

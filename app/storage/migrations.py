from pathlib import Path


def migrations_path() -> Path:
    return Path(__file__).resolve().parents[2] / "migrations"


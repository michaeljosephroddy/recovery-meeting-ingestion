import json

from app.config import Settings
from app.scraping.artifact_import import import_artifact_summary


def test_artifact_import_infers_timezone_from_source_metadata_country(tmp_path) -> None:
    source_dir = tmp_path / "ca-ireland"
    source_dir.mkdir()
    summary_path = source_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "source_id": "ca-ireland",
                "source_url": "https://caireland.example/",
                "status": "succeeded",
                "pages_visited": 1,
                "records_extracted": 1,
                "pages": [
                    {
                        "url": "https://caireland.example/",
                        "final_url": "https://caireland.example/",
                        "extracted": [
                            {
                                "payload": {
                                    "name": "Monday Main",
                                    "day": "Monday",
                                    "time": "7:30 pm",
                                    "city": "Dublin",
                                },
                                "method": "heuristic_table_row",
                                "confidence": 0.95,
                                "signals": ["day", "time", "name"],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = import_artifact_summary(
        summary_path,
        Settings(),
        source_metadata={"country": "Ireland"},
    )

    assert result.ingest.candidates[0].occurrences[0].timezone == "Europe/Dublin"
    assert [flag.code for flag in result.ingest.review_flags] == []


def test_artifact_import_uses_stored_source_config_timezone(tmp_path) -> None:
    source_dir = tmp_path / "ca-arizona"
    source_dir.mkdir()
    summary_path = source_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "source_id": "ca-arizona",
                "source_url": "https://caarizona.example/",
                "status": "succeeded",
                "pages_visited": 1,
                "records_extracted": 1,
                "pages": [
                    {
                        "url": "https://caarizona.example/",
                        "final_url": "https://caarizona.example/",
                        "extracted": [
                            {
                                "payload": {
                                    "name": "Noon Main",
                                    "day": "Tuesday",
                                    "time": "12:00 pm",
                                    "city": "Phoenix",
                                },
                                "method": "heuristic_table_row",
                                "confidence": 0.95,
                                "signals": ["day", "time", "name"],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = import_artifact_summary(
        summary_path,
        Settings(),
        source_metadata={"config": {"timezone": "America/Phoenix"}},
    )

    assert result.ingest.candidates[0].occurrences[0].timezone == "America/Phoenix"
    assert [flag.code for flag in result.ingest.review_flags] == []

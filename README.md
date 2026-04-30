# Recovery Meeting Ingestion

Python service for discovering, ingesting, normalizing, reviewing, and exporting recovery meeting data for SoberSpace.

The execution plan is:

- `exec_plans/001_global_meeting_ingestion.md`

## Local Development

Use a database that is separate from the SoberSpace app database:

```bash
createdb recovery_meeting_ingestion_dev
export DATABASE_URL=postgresql:///recovery_meeting_ingestion_dev
```

Create a virtual environment and install the project:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Run checks:

```bash
ruff check .
pytest
mypy app
```

Current fixture-backed dry runs:

```bash
python -m app.cli discover-sources --fellowship aa --dry-run
python -m app.cli ingest-source --source-id example-aa-feed --dry-run
python -m app.cli export-snapshot --dry-run
```

Operational notes:

- [EC2 operations](docs/operations_ec2.md)
- [SoberSpace integration](docs/soberspace_integration.md)

Run local Postgres integration tests after applying migrations:

```bash
DATABASE_URL=postgresql:///recovery_meeting_ingestion_dev alembic upgrade head
RUN_DB_TESTS=1 DATABASE_URL=postgresql:///recovery_meeting_ingestion_dev pytest tests/test_repositories_db.py
```

# Recovery Meeting Ingestion

Python service for discovering, ingesting, normalizing, reviewing, and exporting recovery meeting data for SoberSpace.

The active execution plan is:

- `exec_plans/002_browser_first_local_site_scraper.md`

`exec_plans/001_global_meeting_ingestion.md` contains the original durable ingestion plan, but the
default operational workflow is now browser-first scraping of local service-body websites.

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
.venv/bin/ruff check app tests
.venv/bin/pytest
.venv/bin/mypy app
```

For interactive local-site scraping, install the Playwright extra and browser runtime:

```bash
pip install -e ".[playwright]"
playwright install chromium
```

Current fixture-backed dry runs:

```bash
python -m app.cli discover-sources --fellowship aa --dry-run
python -m app.cli scrape-source --source-id example-aa --fixture tests/fixtures/static_meetings.html --dry-run
python -m app.cli export-snapshot --dry-run
```

Default browser-first production flow:

```bash
python -m app.cli discover-sources --fellowship aa --no-dry-run
python -m app.cli scrape-all --fellowship aa --no-dry-run
python -m app.cli export-snapshot --no-dry-run
```

Operational notes:

- [EC2 operations](docs/operations_ec2.md)
- [SoberSpace integration](docs/soberspace_integration.md)

Run local Postgres integration tests after applying migrations:

```bash
DATABASE_URL=postgresql:///recovery_meeting_ingestion_dev alembic upgrade head
RUN_DB_TESTS=1 DATABASE_URL=postgresql:///recovery_meeting_ingestion_dev pytest tests/test_repositories_db.py
```

Browser-backed crawler tests are opt-in because they require Playwright Chromium:

```bash
RUN_BROWSER_TESTS=1 .venv/bin/pytest tests/test_browser_scraper.py
```

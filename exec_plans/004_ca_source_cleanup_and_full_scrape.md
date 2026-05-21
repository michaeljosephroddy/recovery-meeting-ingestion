# CA Source Cleanup And Full Scrape

## Goal

Clean the CA source registry so full CA scraping targets actual local meeting sites, then run a full CA scrape/import and report remaining gaps.

## Plan

1. Tighten CA discovery URL classification to reject direct app/store/map/meeting links and internal CA Online non-source pages.
2. Add a cleanup command that identifies existing invalid CA local source rows and can delete them safely.
3. Add tests for the new CA source filtering behavior.
4. Run static checks and tests.
5. Clean the local registry, run the full CA scrape, import artifacts, and summarize coverage/failures.

## Acceptance Criteria

- CA discovery no longer registers CA Online committee/store/app pages as local service-body sources.
- Existing invalid CA source rows can be listed and removed from the local registry.
- The command defaults to dry-run and does not delete rows with existing canonical meetings unless explicitly requested.
- Full CA scrape results distinguish successful sources, zero-candidate sources, and failed sources.

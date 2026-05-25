# NA Manual Follow-Ups - 2026-05-25

These sources are intentionally outside the automated NA import path after the
2026-05-25 completion pass. They should not block publication of
`snapshots/meetings-2026-05-25T113118Z.json`.

## Broad/Duplicate-Risk Exclusions

- `na-1cf592320452` South Coastal Area, South Carolina
  - Current reachable data: CRNA regional-scale meeting table.
  - Disposition: exclude from area import to avoid duplicate regional ownership.
- `na-1fedb2223571` Bringing Freedom East Area, Colorado
  - Current reachable data: 240-row Colorado regional PDF from `nacolorado.org`.
  - Disposition: exclude from area import until an area-scoped schedule is found.
- `na-9a13a07d619f` River Coast Area, Florida
  - Current reachable data: 460-row Florida Region PDF covering Florida, Bermuda,
    and Trinidad and Tobago.
  - Disposition: exclude from area import until an area-scoped schedule is found.

## Human Follow-Up Required

- `na-98fad1257a15` UK Farsi Groups Area
  - Blocker: relevant UKNA meetings/online subdomains return Cloudflare challenge
    pages; accessible UKNA home page does not expose a Farsi/Persian feed.
  - Needed: direct schedule URL, feed endpoint, or source-owner access path.
- `na-5ae7212e49ca` Trinidad and Tobago Area
  - Blocker: current page exposes Google My Maps places but no meeting days or
    times; old My Maps KML endpoint returned 404.
  - Needed: current schedule source, not only location points.
- `na-287fa3467f36` Montreal English Area
  - Blocker: current source remains zero after parser fixes; old public calendar
    feed/list appears stale.
  - Needed: current replacement schedule URL or feed.
- `na-800d03d9c194` Western Massachusetts Area
  - Blocker: current meeting page remains zero after parser/source-specific fixes.
  - Needed: source investigation or a current endpoint/list from the area.

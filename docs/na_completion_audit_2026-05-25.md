# NA Completion Audit - 2026-05-25

Final audited candidates: 36
Resolved after source-specific parser work: 29
Remaining audited candidates: 7

## Classification Counts
- source_specific_manual_or_parser_followup: 4
- broad_or_duplicate_risk: 3

## Final Disposition

The remaining 7 items are not publication blockers. The 3 broad/duplicate-risk sources
are intentionally excluded from automated import because the currently reachable data is
regional or statewide and would create duplicate or wrongly owned meetings. The 4 manual
items require a human-provided current schedule URL, feed, or access path before another
automated import attempt is justified.

## Original Audit Buckets
- possible_missed_structured_feed: 18
- possible_pdf_or_printable: 8
- parser_gap_candidate: 1
- possible_embed_or_calendar: 4

## Resolved

- `na-57cee7d3ba6b` Brazil / Sao Paulo: 10 Brazil Region - implemented direct `cade-o-grupo` AJAX parsing for `na.org.br`; persisted 1,261 active occurrence records with no review flags.
- `na-0311a0916a61` Brazil / Minas Gerais: CSA Grande BH - implemented direct `cade-o-grupo` AJAX parsing scoped to metadata city `Belo Horizonte`; persisted 44 active occurrence records with no review flags.
- `na-be52cc6d882d` Ukraine: Ukraine Region - implemented WordPress block parsing for Ukrainian-language foreign groups; persisted 11 active occurrence records with no review flags.
- `na-a78c156fa126` United States / Maryland: Ocean Gateway Area - implemented direct BMLT service body import for service body `38`; persisted 33 active records with no review flags.
- `na-f89bb33e4f09` United States / New York: Southern Adirondack Mountain Miracles Area - implemented direct BMLT service body import for service body `162`; persisted 16 active records with no review flags.
- `na-5f238c81d49f` Brazil / Rio Grande do Sul: Litoral Norte Gaucho Area - implemented source-specific `cade-o-grupo` AJAX recovery scoped to the Google Site's listed Litoral groups; persisted 16 active occurrence records with no review flags.
- `na-95708177aea5` United States / Oklahoma: Red River Region (Southern OK & North TX) - recovered the current `www.redriverna.com` OklaTex meeting schedule PDF and filtered to Oklahoma rows; persisted 6 active occurrence records with no review flags.
- `na-a9fe8b207548` United States / Texas: Red River Region (Southern OK & North TX) - recovered the current `www.redriverna.com` OklaTex meeting schedule PDF and filtered to Texas rows; persisted 29 active occurrence records with no review flags.
- `na-6ae02f8589f4` United States / Pennsylvania: Downtown Area - implemented direct BMLT import from `meetings.naworks.org` service body `9`; persisted 17 active records with no review flags.
- `na-ff485154ee5f` United States / New Mexico: Greater Albuquerque Area - implemented direct BMLT import from the BMLT aggregator service body `1955`; persisted 45 active records with no review flags.
- `na-b2575093eb9d` United States / Hawaii: Hawaii Region - implemented direct BMLT import from `na-hawaii.org/bmltmain` regional service body `1`; persisted 147 active records with no review flags.
- `na-07fdcb08f177` United States / Texas: Lone Star Region - English - implemented direct BMLT import from Tomato service body `16`; persisted 623 active records with no review flags.
- `na-0e14cccfb90e` United States / California: Mendocino Country Area - implemented direct BMLT import from Western States Zonal Forum service body `1150`; persisted 42 active records with no review flags.
- `na-7b9dd88bb350` United States / California: Monterey County Area - implemented direct BMLT import from Western States Zonal Forum service body `1152`; persisted 33 active records with no review flags.
- `na-87c9f3b0caef` United States / Missouri: Ozark Area - implemented direct BMLT import from the BMLT aggregator service body `1565`; persisted 60 active records with no review flags.
- `na-94eed0942491` United States / Texas: Tejas Bluebonnet Region - implemented direct BMLT import from `texasoklahomana.org` regional service body `1018`; persisted 589 active records with no review flags.
- `na-80b945d48ccb` United States / West Virginia: Appalachian Area (Atlavista, Appomattox, Lynchburg) - generalized linked `current-meeting-list` PDF recovery; persisted 22 active records with no review flags.
- `na-3e653e4288a3` United States / Kansas: Just for Today Area (SE Kansas) - generalized linked `current-meeting-list` PDF recovery from a cross-site meeting schedule; persisted 60 active records with no review flags.
- `na-90efe8899be9` United States / Oregon: Southern Oregon Area (Ashland, Medford) - generalized button `data-url` current-meeting-list recovery; persisted 40 active records with no review flags.
- `na-3a9a90702ff7` United States / Florida: Palm Coast Area (West Palm Beach) - allowed linked PDF fallback after low-score rendered page candidates are discarded; persisted 81 active records with no review flags.
- `na-c61bddc3eff3` United States / Illinois: Rock River Area (Rockford) - allowed linked PDF fallback after low-score rendered page candidates are discarded; persisted 46 active records with no review flags.
- `na-4d3d6f54f716` United States / Virginia: Outer Limits Area (Suffolk, Courtland, Franklin, Southampton County & Smithfield) - decoded encoded PDF path keywords such as `Meetings%20Updated...pdf`; persisted 5 active records with no review flags.
- `na-41b6e1cb9842` United States / Oklahoma: Eastern Area (Tulsa) - used the Crouton/BMLT service body `42` endpoint directly; persisted 139 active records with no review flags.
- `na-40333db921fd` United States / Connecticut: Connecticut Region - implemented BMLTWF JSON parsing from `ctna.org`; persisted 217 active records with no review flags.
- `na-d29507d2e6d6` United States / Virginia: New River Valley Area - implemented stacked schedule parsing for the current May 2026 page; persisted 11 active records with no review flags.
- `na-741664cfd8df` Philippines: Luzon Area - implemented Weebly time-first schedule parsing; persisted 18 active records with no review flags.
- `na-318bd9c44950` Bermuda: Bermuda Area - implemented WordPress schedule parsing from `/bermuda-meetings/`; persisted 11 active records with no review flags.
- `na-d4eceee5b4d4` Thailand: Thailand Region - implemented index-to-area-page schedule parsing across Thailand meeting pages; persisted 38 active records with no review flags.
- `na-494e4e542045` Belarus: Belarus Area - implemented Russian schedule table parsing across group pages; persisted 98 active records with no review flags.

## Intentionally Excluded Broad-Risk Sources

- `na-1cf592320452` broad_or_duplicate_risk (possible_missed_structured_feed) - United States / South Carolina: South Coastal Area (Greater Southern Charleston) - https://www.crna.org/area-service-committees/south-coastal-area-meeting-schedule/ - diagnostic extracted a regional-scale table; broad-area guard prevented import
- `na-1fedb2223571` broad_or_duplicate_risk (possible_missed_structured_feed) - United States / Colorado: Bringing Freedom East Area (Sterling, Yuma) - https://nacolorado.org/meetings/ - current-list recovery reaches a 240-row Colorado regional PDF, not an area-scoped list; broad-area guard prevents import
- `na-9a13a07d619f` broad_or_duplicate_risk (possible_missed_structured_feed) - United States / Florida: River Coast Area (Hernando County) - https://rivercoastareana.org/ - current-list recovery reaches the 460-row Florida Region PDF covering Florida, Bermuda, and Trinidad and Tobago; broad-area guard prevents import

## Manual Follow-Up Sources

- `na-98fad1257a15` source_specific_manual_or_parser_followup (parser_gap_candidate) - United Kingdom / England: UK Farsi Groups Area - https://www.ukna.org/ - meetings/online subdomains return Cloudflare challenge pages; accessible UKNA home page does not expose a Farsi/Persian feed or link
- `na-5ae7212e49ca` source_specific_manual_or_parser_followup (possible_embed_or_calendar) - Trinidad & Tobago: Trinidad and Tobago Area - https://naservicestrinidad.webstarts.com/products.html - page exposes a Google My Maps embed with meeting places but no visible schedule; old My Maps KML endpoint returned 404, so this remains manual/location-only until a schedule source is found
- `na-287fa3467f36` source_specific_manual_or_parser_followup (possible_missed_structured_feed) - Canada / Quebec: Montreal English Area - https://www.eanamontreal.org/meetings1 - retried after current fixes and still returned zero
- `na-800d03d9c194` source_specific_manual_or_parser_followup (possible_missed_structured_feed) - United States / Massachusetts: Western Massachusetts Area - https://westernmassna.org/meetings/ - retried after current fixes and still returned zero

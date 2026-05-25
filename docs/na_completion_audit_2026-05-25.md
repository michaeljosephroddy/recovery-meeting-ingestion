# NA Completion Audit - 2026-05-25

Final audited candidates: 36
Resolved after source-specific parser work: 16
Remaining audited candidates: 20

## Classification Counts
- source_specific_manual_or_parser_followup: 19
- broad_or_duplicate_risk: 1

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

## Evidence

- `na-1cf592320452` broad_or_duplicate_risk (possible_missed_structured_feed) - United States / South Carolina: South Coastal Area (Greater Southern Charleston) - https://www.crna.org/area-service-committees/south-coastal-area-meeting-schedule/ - diagnostic extracted a regional-scale table; broad-area guard prevented import
- `na-98fad1257a15` source_specific_manual_or_parser_followup (parser_gap_candidate) - United Kingdom / England: UK Farsi Groups Area - https://www.ukna.org/ - meetings/online subdomains return Cloudflare challenge pages; accessible UKNA home page does not expose a Farsi/Persian feed or link
- `na-5ae7212e49ca` source_specific_manual_or_parser_followup (possible_embed_or_calendar) - Trinidad & Tobago: Trinidad and Tobago Area - https://naservicestrinidad.webstarts.com/products.html - page exposes a Google My Maps embed with meeting places but no visible schedule; old My Maps KML endpoint returned 404, so this remains manual/location-only until a schedule source is found
- `na-494e4e542045` source_specific_manual_or_parser_followup (possible_missed_structured_feed) - Belarus: Belarus Area (Brest) - https://na-rb.by - retried after current fixes and still returned zero
- `na-318bd9c44950` source_specific_manual_or_parser_followup (possible_missed_structured_feed) - Bermuda: Bermuda Area - https://www.nabermuda.org - retried after current fixes and still returned zero
- `na-287fa3467f36` source_specific_manual_or_parser_followup (possible_missed_structured_feed) - Canada / Quebec: Montreal English Area - https://www.eanamontreal.org/meetings1 - retried after current fixes and still returned zero
- `na-d4eceee5b4d4` source_specific_manual_or_parser_followup (possible_missed_structured_feed) - Thailand: Thailand Region - https://na-thailand.org/meetings/ - retried after current fixes and still returned zero
- `na-1fedb2223571` source_specific_manual_or_parser_followup (possible_missed_structured_feed) - United States / Colorado: Bringing Freedom East Area (Sterling, Yuma) - https://nacolorado.org/meetings/ - retried after current fixes and still returned zero
- `na-40333db921fd` source_specific_manual_or_parser_followup (possible_missed_structured_feed) - United States / Connecticut: Connecticut Region (Serves all of Connecticut) - https://ctna.org/find-a-meeting/ - retried after current fixes and still returned zero
- `na-41b6e1cb9842` source_specific_manual_or_parser_followup (possible_missed_structured_feed) - United States / Oklahoma: Eastern Area (Tulsa) - https://www.eascna.org/?page_id=30 - retried after current fixes and still returned zero
- `na-9a13a07d619f` source_specific_manual_or_parser_followup (possible_missed_structured_feed) - United States / Florida: River Coast Area (Hernando County) - https://rivercoastareana.org/ - retried after current fixes and still returned zero
- `na-800d03d9c194` source_specific_manual_or_parser_followup (possible_missed_structured_feed) - United States / Massachusetts: Western Massachusetts Area - https://westernmassna.org/meetings/ - retried after current fixes and still returned zero
- `na-741664cfd8df` source_specific_manual_or_parser_followup (possible_pdf_or_printable) - Philippines: Luzon Area - https://luzonna.weebly.com/na-meetings.html - retried after current fixes and still returned zero
- `na-80b945d48ccb` source_specific_manual_or_parser_followup (possible_pdf_or_printable) - United States / West Virginia: Appalachian Area (Atlavista, Appomattox, Lynchburg) - https://cvaana.org - retried after current fixes and still returned zero
- `na-3e653e4288a3` source_specific_manual_or_parser_followup (possible_pdf_or_printable) - United States / Kansas: Just for Today Area (SE Kansas) - https://www.jftareana.net/ - retried after current fixes and still returned zero
- `na-d29507d2e6d6` source_specific_manual_or_parser_followup (possible_pdf_or_printable) - United States / Virginia: New River Valley Area (Giles, Pulaski, Montgomery) - https://nrvana.org/meetings - retried after current fixes and still returned zero
- `na-4d3d6f54f716` source_specific_manual_or_parser_followup (possible_pdf_or_printable) - United States / Virginia: Outer Limits Area (Suffolk, Courtland, Franklin, Southampton County & Smithfield) - https://outerlimitsareana.com/meetings-list - retried after current fixes and still returned zero
- `na-3a9a90702ff7` source_specific_manual_or_parser_followup (possible_pdf_or_printable) - United States / Florida: Palm Coast Area (West Palm Beach) - https://www.palmcoastna.org/ - retried after current fixes and still returned zero
- `na-c61bddc3eff3` source_specific_manual_or_parser_followup (possible_pdf_or_printable) - United States / Illinois: Rock River Area (Rockford) - https://www.rockriverna.org - retried after current fixes and still returned zero
- `na-90efe8899be9` source_specific_manual_or_parser_followup (possible_pdf_or_printable) - United States / Oregon: Southern Oregon Area (Ashland, Medford) - https://www.southernoregonna.org/ - retried after current fixes and still returned zero

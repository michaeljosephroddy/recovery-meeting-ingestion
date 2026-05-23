# CA Warning Audit - 2026-05-23

Snapshot candidate:

- Path: `snapshots/meetings-2026-05-23T220707Z.json`
- Snapshot DB row: `de3e6f4b-4d52-4762-812c-287a67283559`
- Meetings: `5,136`
- Blocking review errors: `0`

Open warning flags after final CA artifact replay:

- `possible_personal_contact`: `462` warnings across `43` sources.
- `possible_private_online_credential`: `395` warnings across `42` sources.
- `scrape_low_confidence`: `155` warnings across `20` sources.
- `missing_timezone`: `148` warnings across `11` sources.

Highest-volume warning sources:

- CA Online, `https://ca-online.org`: `121` warnings. This is almost entirely online meeting connection details, split between contact-like text and meeting credentials.
- Cleveland CA, `http://clevelandca.org`: `104` warnings. Mixed low-confidence rows, missing timezone, contact-like text, and credentials.
- Southern Ontario, `https://www.ca-on.org/`: `75` warnings. Mostly contact-like text and online credentials.
- Scotland, `http://www.cascotland.org.uk/`: `75` warnings. Mostly contact-like text and online credentials.
- Los Angeles, `http://www.ca4la.org/`: `71` warnings. Mostly online credentials and contact-like text.
- Colorado, `http://www.ca-colorado.org/`: `47` warnings. Primarily low-confidence scrape records.
- Sweden, `http://ca-sweden.se/`: `46` warnings. Mostly contact-like text and credentials.
- Orange County, `https://orangecountyca.info/`: `45` warnings. Mixed credentials, contact-like text, low confidence, and missing timezone.

Interpretation:

The remaining warnings are not blockers for snapshot export. They are publication-policy prompts.

The contact and credential warnings frequently overlap with public online meeting access details. The latest classifier no longer treats Zoom-style meeting IDs as personal phone numbers, but true service contacts and personal-looking phone numbers remain flagged. The credential warnings identify public passcodes/passwords/meeting IDs that may be intentionally published by service bodies but should be a deliberate downstream choice.

The missing timezone warnings are concentrated in a small number of sources. Some are local US sites without region metadata, such as Cleveland, Washington, and Orange County. Others are online/global listings where one timezone may be inherently ambiguous. These warnings do not block export, but they can cause downstream local-time rendering errors if consumers convert from `UTC`.

The low-confidence warnings are concentrated in Colorado, Cleveland, Arkansas, Arizona, DC/MD/VA, and Akron. These should be sampled visually before a high-confidence public launch, but the records were still normalized and included.

Recommended publish decision:

Publish `snapshots/latest.json` only if SoberSpace is willing to display service-body-published online credentials as meeting connection information. Otherwise, add a redaction pass for credential-bearing fields before downstream import.

Recommended follow-up work:

1. Add source-level timezone metadata for Cleveland, Washington, Orange County, Tennessee, Akron, and Pennsylvania.
2. Sample Colorado and Cleveland low-confidence records against their source pages and add source-specific parsing if the shape is systematically wrong.
3. Decide whether `phone_join_info` should preserve passcodes/passwords, redact them, or split credentials into a sensitive field that SoberSpace can choose not to display.

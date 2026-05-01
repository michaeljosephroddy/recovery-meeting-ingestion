# Data Policy

The ingestion service may store raw source payloads for audit and parser recovery. Exported snapshots
must exclude raw payloads, personal contact details, raw Zoom passcodes, and unreviewed private online
meeting credentials.

Browser scrape artifacts can include rendered HTML, screenshots, action traces, and extracted raw
payloads from public service-body sites. Treat `scrape_artifacts/` as operational evidence, not a
public export. Do not publish it to SoberSpace users. The snapshot export remains the reviewed public
boundary.

Scraped records include confidence metadata. Low-confidence records create review flags, and
very-low-confidence records are kept out of canonical candidate storage by default so ambiguous page
text is not silently published.

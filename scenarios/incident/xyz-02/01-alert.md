---
incident: xyz-02
document: 01-alert
classification: [timeline, internal-identifier]
---

# Monitoring alert — TLS handshake failures on the API gateway

**Alert id:** XYZ-2141
**Fired:** Tuesday 00:03
**Severity:** critical
**Hosts:** api-gw-01, api-gw-02 (API gateway tier)

At 00:00 Tuesday the synthetic monitor for the scheduling API began failing on both gateway hosts with `certificate has expired`. The wildcard certificate for `*.api.xyz.internal`, serial 4F:2B:9C, expired at 00:00. All API calls from customer integrations were rejected at the TLS layer from that moment.

At 00:07 the on-call engineer (Priya Natarajan) acknowledged the alert and opened incident XYZ-2142. Web calendar traffic, which terminates on the web tier (web-app-01 to web-app-03) with a different certificate, was unaffected.

The alert cleared at 03:40 when a renewed certificate was deployed to both gateway hosts. The incident bridge was opened at 00:20.

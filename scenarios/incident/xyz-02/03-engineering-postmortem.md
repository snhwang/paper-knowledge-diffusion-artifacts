---
incident: xyz-02
document: 03-engineering-postmortem
classification: [remediation, internal-identifier, timeline]
---

# Engineering postmortem — incident XYZ-2142

**Author:** On-call engineer (Priya Natarajan)

## Timeline of service impact

- 00:00 — certificate expired; scheduling API rejected all customer integration calls. Web calendar unaffected.
- 00:07 — alert acknowledged, incident opened.
- 02:10 — hotfix: a self-signed certificate installed on api-gw-01 and api-gw-02 to restore the API while a vendor-issued certificate was requested. API integrations recovered.
- 02:10 to 02:35 — second outage, mobile only: the mobile app pins the certificate chain and rejected the self-signed certificate, so mobile users could not log in for 25 minutes. Reverted the pinning fallback flag `mobile.pin.strict` to allow the interim chain at 02:35.
- 03:31 — vendor-issued replacement certificate received.
- 03:40 — replacement deployed to both gateway hosts; full service restored. Total API outage 3 h 40 min.

## What was changed

1. Interim self-signed certificate (02:10), replaced by the vendor certificate (03:40).
2. `mobile.pin.strict` set to false at 02:35 to end the mobile outage; must be restored to true once the new chain is confirmed on all app versions (XYZ-2144).
3. Renewal automation `cert-renew` re-enabled on ops-01 with alerting at 30 days and 7 days before any expiry (XYZ-2143).

## Follow-up tickets

- XYZ-2143: renewal automation and expiry alerts (done).
- XYZ-2144: restore strict pinning after chain rollout.
- XYZ-2145: inventory of every certificate in production with expiry dates.
- XYZ-2146: revoke the interim self-signed certificate from the trust store (done).

## Fragile

Strict pinning is currently off. Until XYZ-2144 closes, the mobile app accepts any chain the gateway presents that is rooted in the trust store.

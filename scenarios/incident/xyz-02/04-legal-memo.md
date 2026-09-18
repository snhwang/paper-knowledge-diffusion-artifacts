---
incident: xyz-02
document: 04-legal-memo
classification: [privileged, exposure]
---

# Privileged and confidential — legal assessment, incident XYZ-2142

**Author:** Legal and compliance counsel (Marta Lindqvist)
**Prepared for:** Incident commander.

## Exposure

This is an availability incident. Pending security's concurrent-access review, my assessment is that no personal data was accessed. Until that review is confirmed (expected Wednesday morning) we must not assert externally that no data was at risk; we may say that we have no indication of any data being accessed.

## Obligations

- Regulatory: none. No personal-data breach; no notification duty in either district.
- Contractual: 9 customers are on the Premium service level (99.9% monthly availability). An outage of 3 h 40 min breaches that level for the month, entitling each to a service credit of 5% of the monthly fee under clause 7.2 of the Premium schedule. Total exposure is approximately $4,200. The remaining 52 affected customers are on the Standard schedule, which carries no credit.
- One Premium customer, Northgate Medical Group, has a contractual right to a written root-cause report within 10 business days (clause 7.4).

## What may and may not be stated externally

- Do not state "no data was at risk" as fact until security's review is confirmed.
- Do not name the vendor or the certificate details.
- It may be stated that the outage was caused by an expired security certificate, that it was not an attack, and that it has been fixed.

## Recommendation

Issue the Premium credits proactively rather than on request; it costs the same and avoids nine separate disputes. Send Northgate the root-cause report by the deadline.

---
incident: xyz-02
document: 06-status-page-draft
classification: [public, timeline]
---

# Status page — draft for legal review

**Author:** Communications lead (Hannah Whitfield)

## Tuesday 09:00 — Resolved: API integration outage

Between midnight and 03:40 on Tuesday, customers booking through the API integration were unable to connect. The cause was an expired security certificate on our side. This was not an attack. Mobile app users were also unable to log in for about 25 minutes, from 02:10 to 02:35, while we applied a fix.

Timeline:

- 00:00: API integration connections began failing.
- 02:10: an interim fix restored the integration; mobile app logins were briefly affected.
- 02:35: mobile app logins restored.
- 03:40: permanent fix deployed; all services normal.

We have no indication that any data was accessed. Web calendar bookings were unaffected throughout.

We will post a follow-up on Wednesday by 12:00 with the results of our review.

## Notes for legal

- We have said "no indication that any data was accessed", not "no data was at risk", pending the security review.
- We have not named the vendor or the certificate.
- Please confirm the Wednesday 12:00 follow-up time.

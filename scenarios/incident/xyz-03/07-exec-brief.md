---
incident: xyz-03
document: 07-exec-brief
classification: [exposure, timeline, remediation]
---

# Executive brief — incident XYZ-2202, Friday 17:00

**Author:** Incident commander (Elena Marsh)

## Summary

A departing account manager exported the business contact details of staff at 212 customer clinics on Thursday evening and emailed the file to a personal address. No patient data was involved. Access was revoked Friday morning. The export function had no audit logging and no approval step; both are now in place.

## Decisions taken

- Courtesy notice to all 212 customers on Monday; contractual notices to the three customers whose contracts require them, within their 7-day window.
- Letter from outside counsel to the former employee on Monday demanding deletion and certification.
- No regulator notification, on legal's assessment; the decision to be documented.
- Exports of customer data now require a second approver and are logged.

## Open items and owners

| Item | Owner | Due |
|---|---|---|
| Courtesy notice to all customers | Communications, Legal | Monday 10:00 |
| Contractual notices to the three customers | Legal | next Friday 08:50 |
| Counsel's letter to the former employee | Legal | Monday |
| Exemption for the nightly CRM sync | Engineering | Monday 02:00 |
| Audit-logging review of the admin console | Engineering | three weeks |

## Cost so far

About 22 engineering hours, outside counsel, and an estimated 30 support hours for customer questions.

---
incident: xyz-01
document: 07-exec-brief
classification: [exposure, timeline, remediation]
---

# Executive brief — incident XYZ-2082, Tuesday 14:00

**Author:** Incident commander (Elena Marsh)

## Summary

An attacker used a flaw in our PDF export feature to obtain a read-only database credential and read the appointment lists of 14 clinics over a 19-hour window ending 02:31 Tuesday. About 3,100 individuals' names and appointment times were exposed. The attack is contained, the credential is rotated, the flaw is patched, and service is fully restored as of 12:15.

## Decisions taken

- Export feature disabled 03:05 to 12:15 rather than leaving the flaw exposed.
- Affected clinics to be notified Wednesday morning by their account managers; regulator notification in the Northern District by Thursday.
- Outside counsel retained for the regulator filing.
- The affected application host is to be rebuilt before returning to service.

## Open items and owners

| Item | Owner | Due |
|---|---|---|
| Written notice to the 14 clinics | Legal, Support | Wednesday 09:00 |
| Northern District regulator notification | Legal | Friday 09:10 |
| Narrow the emergency egress rule before Sunday's analytics export | Engineering | Saturday |
| Dependency scanning in CI | Engineering | two weeks |
| Public status page update | Communications | Wednesday 17:00 |

## Cost so far

Roughly 40 engineering hours, outside counsel retainer, and an estimated 60 support hours over the coming week. No service credits are contractually due, since the API itself stayed available.

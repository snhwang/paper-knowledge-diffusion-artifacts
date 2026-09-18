---
incident: xyz-04
document: 07-exec-brief
classification: [exposure, timeline, remediation]
---

# Executive brief — incident XYZ-2300, Tuesday 12:00

**Author:** Incident commander (Elena Marsh)

## Summary

Our SMS reminder provider suffered a breach in which a week of message logs was accessed, including reminders we sent for 88 clinics: about 27,000 patients' phone numbers, first names, clinic names and appointment times. No XYZ system was accessed. Text reminders are paused, email reminders are running where possible, and the clinics must be notified by Wednesday afternoon so they can meet their own obligations.

## Decisions taken

- SMS reminders stay off until the provider attests to fixed controls.
- Notify all 88 clinics by Wednesday 15:10 with per-clinic counts.
- Put the provider on notice of a claim under our contract this week.
- Reminders no longer carry the clinic name, on either channel.
- Evaluate a second SMS provider.

## Open items and owners

| Item | Owner | Due |
|---|---|---|
| Clinic notifications with per-clinic counts | Legal, Support | Wednesday 15:10 |
| Public update | Communications | Wednesday 12:00 |
| Notice of claim to the provider | Legal | Friday |
| Printable reminder lists for clinics without email | Engineering, Support | Wednesday |
| Second-provider evaluation | Engineering | one month |

## Cost so far

About 26 engineering hours, outside counsel for the claim, and an estimated 80 support hours across the clinic notifications. Expected recovery from the provider is limited by its contract.

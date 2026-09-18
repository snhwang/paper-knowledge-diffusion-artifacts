---
incident: xyz-04
document: 03-engineering-postmortem
classification: [remediation, internal-identifier, timeline]
---

# Engineering postmortem — incident XYZ-2300

**Author:** On-call engineer (Priya Natarajan)

## Timeline

- Monday 15:10 — vendor notice received.
- Monday 15:40 — Relay API key rotated on sms-relay-01 (XYZ-2302).
- Monday 16:00 — SMS reminders suspended via `reminders.sms.enabled=false` (XYZ-2303).
- Monday 17:30 — email reminders enabled for every clinic that has patient email addresses on file, using the existing email reminder template.
- Tuesday 09:00 — reminder template changed to drop the clinic name (XYZ-2304), ready for when SMS resumes.

## What was changed

1. Relay API key rotated; the old key is dead at Relay's end.
2. SMS reminder channel disabled behind the flag; email channel switched on where possible.
3. Reminder template: first name, date and time only. The clinic name is removed from both SMS and email templates (XYZ-2304).
4. A vendor attestation check added to the SMS enable path: the flag cannot be turned back on until the `vendor.relay.attested` setting is true (XYZ-2305).

## Follow-up tickets

- XYZ-2306: 31 clinics have no patient email addresses on file and currently get no reminders at all; offer them a printable reminder list from the calendar until SMS resumes.
- XYZ-2307: evaluate a second SMS provider so the channel does not depend on one vendor.
- XYZ-2308: quarterly review of what personal data each vendor integration transmits.

## Fragile

Clinics without patient emails are without reminders. No-show rates for those clinics will rise while SMS is off.

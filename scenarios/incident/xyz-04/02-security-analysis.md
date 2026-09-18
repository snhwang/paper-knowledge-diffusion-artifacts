---
incident: xyz-04
document: 02-security-analysis
classification: [exploit-detail, internal-identifier]
---

# Security analysis — Relay Messaging breach, XYZ exposure

**Author:** Security lead (Daniel Okafor)
**Status:** XYZ systems not compromised; exposure through the vendor confirmed Tuesday 11:00

## What the vendor says happened

Relay's notice attributes the access to credential stuffing against their customer support portal: an attacker used passwords leaked elsewhere to log in as Relay support staff and export message logs. The portal did not enforce a second factor for support accounts. Relay says the access ran from the previous Tuesday 03:00 to Sunday 22:00 and has since been closed. These are Relay's findings; we have no independent view of their systems.

## What XYZ sent through Relay in the window

- 41,600 appointment reminder messages to approximately 27,000 distinct phone numbers, on behalf of 88 clinics.
- Each message contained the patient's first name, the clinic's name, and the appointment date and time. No surnames, no clinical content, no links.

Counts are from our own send logs on sms-relay-01, not from Relay.

## XYZ's own systems

- No sign of access to sms-relay-01 or to any XYZ system. The Relay API key `rk_live_…3f9e` could not have been read from Relay's message logs, but it was rotated at 15:40 as a precaution (XYZ-2302).
- Reminders suspended at 16:00 by feature flag `reminders.sms.enabled=false` (XYZ-2303).

## Indicators

- Any use of the old key after 15:40 Monday (all attempts should fail at Relay).
- Reports from clinics of patients receiving texts that quote a clinic name and an appointment time but ask for payment or a link click: that is the likely misuse of these logs.

## Recommendation

Keep SMS reminders off until Relay provides a written attestation that support-portal access now requires a second factor and that the exported logs have been contained. Reduce what reminders carry: the clinic name is not needed for the reminder to be useful.

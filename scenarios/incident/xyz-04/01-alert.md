---
incident: xyz-04
document: 01-alert
classification: [timeline, internal-identifier]
---

# Vendor breach notification — SMS reminder provider

**Alert id:** XYZ-2301 (raised by vendor management on receipt of the notice)
**Received:** Monday 15:10
**Severity:** high
**Vendor:** Relay Messaging, account ACC-9107, integrated through sms-relay-01

At 15:10 Monday, Relay Messaging notified XYZ by email that an unauthorised party had accessed message logs in Relay's support portal between the previous Tuesday and Sunday. Relay's notice states that XYZ's account, ACC-9107, was among those whose logs were accessed, and that the logs include recipient phone numbers and message text for the period.

XYZ uses Relay to send appointment reminder text messages on behalf of clinic customers. The integration runs from sms-relay-01 using API key `rk_live_…3f9e`.

At 15:25 the security lead acknowledged the notice. At 15:40 the Relay API key was rotated (ticket XYZ-2302). At 16:00 SMS reminders were suspended. The incident bridge was opened at 16:15.

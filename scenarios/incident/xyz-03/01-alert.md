---
incident: xyz-03
document: 01-alert
classification: [timeline, internal-identifier]
---

# Data-loss-prevention alert — outbound customer contact export

**Alert id:** XYZ-2201
**Fired:** Thursday 17:42
**Severity:** high
**Source:** dlp-01 (mail DLP), rule DLP-77 (customer data in outbound attachments)

At 17:42 Thursday the mail DLP system flagged an outbound message from an internal mailbox to a personal webmail address carrying a 2.3 MB attachment, `customers_contacts_export.csv`. The sender was employee id E-4471, an account manager whose last working day was scheduled for Saturday. The attachment matched the customer-contact pattern on 1,880 rows.

The message had already been delivered when the rule fired; DLP-77 is configured to alert, not block, for attachments under 5 MB.

At 08:50 Friday the security lead reviewed the alert. At 09:15 mailbox access for E-4471 was suspended and at 09:20 the SSO account was disabled (ticket XYZ-2203). The incident bridge was opened at 09:30 Friday.

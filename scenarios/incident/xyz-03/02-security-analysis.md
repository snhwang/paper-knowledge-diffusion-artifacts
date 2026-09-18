---
incident: xyz-03
document: 02-security-analysis
classification: [exploit-detail, internal-identifier]
---

# Security analysis — unauthorised export of customer contacts by a departing employee

**Author:** Security lead (Daniel Okafor)
**Status:** access revoked Friday 09:20; scope confirmed Friday 14:00

## What was taken

The file `customers_contacts_export.csv` contains 1,880 records covering 212 customer clinics: clinic staff names, work email addresses, work phone numbers and the clinic's account tier. It contains no patient data and no credentials.

## How

The internal admin console (admin-web-01) has an "Export contacts" function available to every account manager. E-4471 invoked it at 17:31 Thursday from the office network, saved the CSV, and emailed it to a personal address at 17:42. The export function wrote no audit record: audit logging was implemented for edits but never for exports. The 17:31 timestamp comes from the web server access log on admin-web-01, matched by session id.

## Indicators

- DLP-77 hits from any internal mailbox with customer-contact patterns.
- Calls to `/admin/contacts/export` on admin-web-01 outside the CRM sync window (02:00 to 02:30).
- Any login attempt by E-4471 after 09:20 Friday (all should fail).

## Containment and assessment

Mailbox and SSO disabled; the personal address is recorded for legal. No other exports by this user in the 90-day access-log retention window. No evidence the file went anywhere beyond the personal mailbox; that cannot be verified from our side. Copies on the office workstation (ws-0412) were removed and the workstation re-imaged Friday 15:00.

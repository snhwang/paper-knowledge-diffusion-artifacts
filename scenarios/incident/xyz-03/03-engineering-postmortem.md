---
incident: xyz-03
document: 03-engineering-postmortem
classification: [remediation, internal-identifier, timeline]
---

# Engineering postmortem — incident XYZ-2202

**Author:** On-call engineer (Priya Natarajan)

No service impact. This postmortem covers the control gaps and what was changed.

## Timeline

- Thursday 17:31 — export made from admin-web-01.
- Thursday 17:42 — DLP alert (not block).
- Friday 09:20 — account disabled.
- Friday 13:30 — audit logging deployed for the export function.
- Friday 16:00 — export function restricted behind a second-approver step.

## What was changed

1. Audit logging for `/admin/contacts/export`: user, time, row count, filter (XYZ-2204).
2. Export now requires approval by a second account manager or a team lead before the file is produced (XYZ-2205).
3. DLP-77 changed from alert to block for attachments matching customer-contact patterns at any size (XYZ-2206).
4. Exports over 500 rows now produce a watermarked file carrying the requesting user id.

## Follow-up tickets

- XYZ-2207: the approval step currently blocks the nightly CRM sync, which calls the same export path; an exemption for the service account is needed before Monday 02:00.
- XYZ-2208: review every admin-console function for missing audit logging.
- XYZ-2209: automatic access removal on an employee's confirmed last day rather than the following Monday.

## Fragile

Until XYZ-2207 closes, the CRM sync will fail nightly and the sales team's pipeline view will be stale.

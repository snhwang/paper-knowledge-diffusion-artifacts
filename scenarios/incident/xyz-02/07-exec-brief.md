---
incident: xyz-02
document: 07-exec-brief
classification: [exposure, timeline, remediation]
---

# Executive brief — incident XYZ-2142, Tuesday 11:00

**Author:** Incident commander (Elena Marsh)

## Summary

The certificate securing our API integration expired at midnight because the renewal automation had been switched off in July and never restored. The integration was down for 3 h 40 min, affecting 61 customers; an interim fix caused a further 25-minute outage for mobile app users. No attack, and no indication that any data was accessed; security's review is due Wednesday morning.

## Decisions taken

- Issue service credits to the nine Premium customers proactively, about $4,200 in total.
- Send Northgate Medical Group the written root-cause report it is entitled to, within 10 business days.
- Renewal automation restored with alerts 30 and 7 days ahead of any expiry.
- Strict mobile certificate pinning to be restored once the new chain is confirmed.

## Open items and owners

| Item | Owner | Due |
|---|---|---|
| Concurrent-access review confirmed | Security | Wednesday 10:00 |
| Public follow-up | Communications | Wednesday 12:00 |
| Premium credits on next invoices | Legal, Support | end of month |
| Root-cause report to Northgate | Engineering, Legal | 10 business days |
| Certificate inventory | Engineering | two weeks |

## Cost so far

About 18 engineering hours, the $4,200 in credits, and an estimated 20 support hours.

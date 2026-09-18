---
incident: xyz-01
document: 02-security-analysis
classification: [exploit-detail, internal-identifier]
---

# Security analysis — PDF export credential disclosure

**Author:** Security lead (Daniel Okafor)
**Status:** contained as of 02:31 Tuesday; root cause confirmed 09:10

## Root cause

The PDF export library used by `xyz-pdfexport` build 4.12.3 carries CVE-2026-90412, a path traversal in the `filename` parameter of the export endpoint. A request of the form `/api/export?filename=../../etc/xyz/db.env` returns the named file inside the generated PDF. The library version was 2.8.1; the fix is in 2.8.4.

## Attack path

1. Between 01:51 and 02:13, 412 export requests with traversal payloads reached sched-app-03 from 203.0.113.9. No other application host received them; the attacker's session was pinned to sched-app-03 by the load balancer.
2. Each request returned `/etc/xyz/db.env`, which holds the read-only replica credential for the scheduling database (`sched_ro`).
3. At 02:02 the same address connected to the replica on `db-replica-02` using `sched_ro` and ran queries against the `appointments` table for 14 clinic tenants.
4. Outbound transfer from the replica to 203.0.113.9 totalled 38 MB before the host was pulled at 02:31.

## Indicators of compromise

- Source address 203.0.113.9
- User agent `curl/8.5.0` on export requests carrying `../` sequences
- Logins as `sched_ro` from any address outside 10.4.0.0/16
- Export requests to sched-app-03 between 01:51 and 02:13

## Containment

The `sched_ro` credential was rotated at 02:38 (ticket XYZ-2083). sched-app-03 remains out of the pool for forensics. The export endpoint is disabled on all hosts until build 4.12.4, which carries library 2.8.4, is deployed. No evidence of writes to any database, and no access to the primary database or to credentials other than `sched_ro`.

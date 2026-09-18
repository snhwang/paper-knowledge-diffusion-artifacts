---
incident: xyz-01
document: 03-engineering-postmortem
classification: [remediation, internal-identifier, timeline]
---

# Engineering postmortem — incident XYZ-2082

**Author:** On-call engineer (Priya Natarajan)

## Timeline of service impact

- 02:31 — sched-app-03 removed from the load balancer. Capacity dropped to two hosts; p95 latency on the scheduling API rose from 180 ms to 310 ms but no requests failed.
- 02:38 — `sched_ro` credential rotated (XYZ-2083). Read replicas reconnected within 90 seconds.
- 03:05 — export endpoint disabled by feature flag `export.enabled=false` on sched-app-01 and sched-app-02. Customers attempting a PDF export received a "temporarily unavailable" message from this point.
- 11:40 — build 4.12.4 deployed to all application hosts. The build pins the PDF library to 2.8.4.
- 12:15 — export endpoint re-enabled after verification. Full service restored.

## What was changed

1. Credential rotation for `sched_ro` and, as a precaution, `sched_rw` (XYZ-2084), although no use of `sched_rw` was observed.
2. Feature flag `export.enabled` added so the export endpoint can be disabled without a deploy.
3. Library upgrade 2.8.1 → 2.8.4 in build 4.12.4.
4. Egress rule added on the application tier denying connections to addresses outside the vendor allow-list (XYZ-2086).

## Follow-up tickets

- XYZ-2085: rebuild sched-app-03 from a clean image before returning it to the pool.
- XYZ-2087: add file-integrity alerts for all files under `/etc/xyz/` on every host, not only db.env.
- XYZ-2088: automated dependency scanning for the PDF library in CI.

## Fragile

The egress rule (XYZ-2086) was written under time pressure and blocks the analytics exporter as a side effect; a narrower rule is needed before the weekly export on Sunday.

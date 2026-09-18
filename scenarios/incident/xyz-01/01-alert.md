---
incident: xyz-01
document: 01-alert
classification: [timeline, internal-identifier]
---

# Monitoring alert — anomalous file reads on sched-app-03

**Alert id:** XYZ-2081
**Fired:** Tuesday 02:14
**Severity:** high
**Host:** sched-app-03 (application tier, scheduling API)

The file-integrity monitor on sched-app-03 reported 412 read operations against `/etc/xyz/db.env` between 01:51 and 02:13, all from the web worker process. The normal rate for that file is zero reads outside service restarts. The process that read the file was the PDF export worker, `xyz-pdfexport`, running build 4.12.3.

At 02:19 the on-call engineer (Priya Natarajan) acknowledged the alert and opened incident XYZ-2082. At 02:26 outbound connections from sched-app-03 to an unfamiliar address, 203.0.113.9, were confirmed in the egress logs. At 02:31 the host was removed from the load balancer pool. The scheduling API remained available on sched-app-01 and sched-app-02.

The alert closed automatically at 02:40 when reads stopped. The incident bridge was opened at 02:45.

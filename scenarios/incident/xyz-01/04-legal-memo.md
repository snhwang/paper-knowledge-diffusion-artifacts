---
incident: xyz-01
document: 04-legal-memo
classification: [privileged, exposure]
---

# Privileged and confidential — legal assessment, incident XYZ-2082

**Author:** Legal and compliance counsel (Marta Lindqvist)
**Prepared for:** Incident commander; not for distribution beyond the incident leadership.

## Exposure

Appointment records for 14 clinic customers were readable by an unauthorised party for 19 hours (Monday 07:30 to Tuesday 02:31, the window during which the vulnerable build was live and the credential valid). The records contain patient names, appointment dates and times, and the clinic name. They do not contain clinical notes, diagnoses, payment details or contact information. Our estimate is 3,100 individuals across the 14 clinics, of whom roughly 2,400 are in the Northern District and 700 in the Eastern District.

## Obligations

- Northern District: notification to the regulator is required within 72 hours of determination of a breach affecting personal data (§ 45 of the data protection statute). Determination was made at 09:10 Tuesday; the deadline is therefore Friday 09:10. Notification to affected individuals is required "without undue delay" where there is a likely risk to them; my assessment is that the risk is moderate (appointment data can reveal that a person attends a particular clinic).
- Eastern District: notification to the regulator within 5 business days (12 CFR 1016 analogue in the district code); individual notification only where financial data is involved, which it is not.
- Contractual: 11 of the 14 clinic contracts require notice to the customer within 48 hours of discovery. Discovery is Tuesday 02:45 (bridge opened); the contractual deadline is Thursday 02:45.

## What may and may not be stated externally

- Do not state that "no patient data was accessed". Patient names and appointment times were accessed.
- Do not describe the technical cause. The vulnerability is not yet patched at other vendors and disclosure is coordinated with the library maintainer.
- It may be stated that a security issue affecting scheduling data at a limited number of clinics was identified and contained on Tuesday, and that affected clinics are being contacted directly.

## Recommendation

Notify the 14 clinics Wednesday morning, the Northern District regulator by Thursday, and prepare individual notices for the Northern District clinics. Retain outside counsel for the Northern District filing.

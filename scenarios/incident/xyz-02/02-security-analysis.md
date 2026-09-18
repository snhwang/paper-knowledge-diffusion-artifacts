---
incident: xyz-02
document: 02-security-analysis
classification: [exploit-detail, internal-identifier]
---

# Security analysis — API gateway certificate expiry

**Author:** Security lead (Daniel Okafor)
**Status:** no attacker; availability incident. Concurrent-access review complete Wednesday 10:00.

## Was this an attack?

No. The certificate for `*.api.xyz.internal` (serial 4F:2B:9C) expired on schedule at 00:00 Tuesday. The renewal job `cert-renew` on ops-01 had been disabled since July (ticket XYZ-1988) after a failed run, and nobody re-enabled it. There is no indication of tampering with the certificate store on either gateway host.

## Concurrent-access review

Because the emergency hotfix deployed a self-signed certificate on api-gw-01 and api-gw-02 between 02:10 and 03:40, clients that skip certificate validation could have been exposed to interception during that window. I reviewed gateway access logs for the window:

- 1,114 API sessions, all from addresses in customers' known ranges or from 10.4.0.0/16.
- No session from an unknown address. No downgrade or renegotiation anomalies.
- The mobile app refused the self-signed certificate (pinning), so it could not have been intercepted; that refusal is what caused the second outage.

Conclusion: no evidence that any data was accessed or intercepted. Confirmed to legal at 10:00 Wednesday.

## Indicators (for the record)

- Gateway log line `TLS handshake failed: certificate has expired` on api-gw-01/02 from 00:00.
- Any future connection presenting serial 4F:2B:9C should be treated as stale.
- Self-signed certificate fingerprint used in the hotfix: `SHA256:9c1e...d41a`; it has been revoked from the trust store (XYZ-2146).

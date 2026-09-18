---
incident: xyz-02
document: 05-customer-impact
classification: [customer-impact, public]
---

# Customer impact summary — Tuesday API outage

**Author:** Customer support lead (Tomas Reyes)

## Who is affected

Sixty-one customers use the API integration to book appointments from their own systems. All 61 were unable to book through the integration from midnight to 03:40 on Tuesday. Customers who book through the web calendar were not affected.

Separately, everyone using the mobile app was unable to log in for about 25 minutes, from 02:10 to 02:35.

## What customers experienced

- API integrations received connection errors for 3 hours 40 minutes.
- Mobile app users saw "could not connect securely" for 25 minutes.
- No appointment data was changed or lost. Bookings made through the web calendar during the outage were recorded normally.

## Workaround during the outage

Appointments could be booked and viewed in the web calendar throughout.

## What customers can do now

- Nothing is required. Integrations and the mobile app are working normally.
- Customers who queued bookings in their own systems during the outage should re-send them; the integration will accept them.
- Customers on the Premium service level will receive a service credit automatically on their next invoice and do not need to request it.

## Support script

"We had an outage of the API integration early on Tuesday, caused by an expired security certificate. It was not an attack, and it has been fixed. Bookings you send now will go through. If you queued bookings during the outage, please re-send them."

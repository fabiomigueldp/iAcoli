**Tool: Manage Recurrences**
Recurrences generate future events automatically based on an RRULE.

- **GET /api/series/recorrencias**: list every recurrence.
- **POST /api/series/recorrencias**: create a new recurrence. Payload:
  - `community`: community code
  - `dtstart_base`: ISO datetime string for the first occurrence
  - `rrule`: recurrence rule string (RFC 5545 style)
  - `quantity`: number of acolytes per event
  - `pool`: optional array of UUID strings for preferred people
- **PATCH /api/series/recorrencias/{recurrence_id}**: update rrule, quantity, or pool. Send only the fields that change.
- **DELETE /api/series/recorrencias/{recurrence_id}**: remove the recurrence.

Building a series with a recurrence usually involves:
1. Create or identify the base event.
2. Add the recurrence with matching `community` and `dtstart_base`.
3. When editing, fetch the recurrence list first so you do not guess the identifier.

**Tool: Manage Existing Events**
Use these endpoints to inspect or modify events already stored in the system.

- **GET /api/events/{identifier}**: fetch event details plus assignments. `{identifier}` accepts a UUID or the `key` string (e.g. `2025-10-12-MAT-REG`).
- **PUT /api/events/{identifier}**: update metadata. Payload keys (all optional):
  - `community` (string)
  - `date` (`YYYY-MM-DD` string)
  - `time` (`HH:MM` string)
  - `quantity` (int > 0)
  - `kind` (string such as `REG`, `SOLENE`)
  - `pool` (array of UUID strings)
  - `dtend` (ISO datetime string)
  Always send only the fields that must change.
- **DELETE /api/events/{identifier}**: remove one event.
- **GET /api/events/{identifier}/pool**: check the current assignment pool.
- **POST /api/events/{identifier}/pool**: replace the pool with a new list. Payload: `{"members": [UUID, ...]}`.
- **DELETE /api/events/{identifier}/pool**: clear the pool entirely.

Workflow suggestions:
1. Find the event using `GET /api/events` or `GET /api/schedule/lista`.
2. Store the identifier in a placeholder.
3. Execute the necessary update/delete/pool call.

When adjusting many fields, consider reading current values first to avoid overwriting important data.

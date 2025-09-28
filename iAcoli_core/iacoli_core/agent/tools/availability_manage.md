**Tool: Manage Availability Blocks**
Use when the user marks someone as unavailable or removes a block.

- **GET /api/people/{person_id}/blocks**: list current blocks. `{person_id}` must be the UUID of the person.
- **POST /api/people/{person_id}/blocks**: add a new block. Payload keys:
  - `start` (ISO datetime, e.g. `2025-11-01T00:00:00`)
  - `end` (ISO datetime, must be after `start`)
  - `note` (string, optional)
- **DELETE /api/people/{person_id}/blocks**: remove blocks. Payload is not used; instead send query parameters through the endpoint string:
  - `?all=true` to remove every block.
  - `?index=1` (1-based) to remove a single block.

Suggested flow:
1. Find the person (`GET /api/people`).
2. Inspect existing blocks if the user says "remove" or "desbloquear".
3. Call POST or DELETE as required using placeholders: `"endpoint": "POST /api/people/{{person.id}}/blocks"`.

Remember: keep datetimes in ISO format and do not mix date-only strings with time.

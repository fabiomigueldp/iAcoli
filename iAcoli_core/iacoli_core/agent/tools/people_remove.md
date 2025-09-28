**Tool: Remove Person**
Delete a person only after confirming with the user.

- **Endpoint:** `DELETE /api/people/{person_id}`
  - `{person_id}` must be a UUID from a previous lookup.
  - No payload required.

Recommended checklist:
1. Locate the person with `GET /api/people` or `GET /api/people/{person_id}`.
2. Confirm the instruction is explicit ("remova", "exclua", "delete").
3. Execute the delete call using the stored identifier.

The core service will also clear assignments and availability blocks related to this person.

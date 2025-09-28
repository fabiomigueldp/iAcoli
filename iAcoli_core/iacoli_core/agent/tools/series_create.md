**Tool: Create Event Series**
Set up a multi-day series that extends an existing base event.

- **Endpoint:** `POST /api/series`
- **Payload:**
  - `base_event_id` (UUID, required): identifier of the original event that anchors the series.
  - `days` (integer, required): number of additional days to create (the base event counts as day 1).
  - `kind` (string, required): event kind for the generated items.
  - `pool` (array of UUID, optional): restrict assignments for every generated event.

Typical workflow:
1. Use **Create Single Event** to insert the first occurrence and capture its `id`.
2. Call this tool with that `id` to generate the remaining days.

The agent must pass the stored identifier using placeholders like `{{create_event.id}}` when chaining calls.
Return the created series metadata.

**Tool: Maintain Event Series**
Use alongside the series creation tool to inspect or adjust multi-day series.

- **GET /api/series**: list every series already defined.
- **PATCH /api/series/{series_id}**: rebase a series onto a new base event and/or replace the pool. Payload keys:
  - `new_base_event_id` (UUID string, optional)
  - `pool` (array of UUID strings, optional)
  At least one field must be provided.
- **DELETE /api/series/{series_id}**: remove the series; generated events stay but are no longer linked.

Before patching or deleting, read the list to capture the right `series_id` and then reference it with a placeholder.

**Tool: Delete Event**
Remove a specific event from the calendar when the user confirms the action.

- **Endpoint:** `DELETE /api/events/{identifier}`
- **Parameters:**
  - `identifier`: use the event key (format `COMMUNITY-YYYYMMDD-HHMM`) or event id string recognised by the API.

Before deleting, confirm that the target event exists, often by combining this tool with `Find Events`.
Return a confirmation message or surface validation errors when the removal fails.

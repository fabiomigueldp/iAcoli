**Tool: Find Events**
Use to locate existing events for follow-up actions or validation steps.

- **How to use:**
  - Call `core_service.list_events()` to retrieve every event from the in-memory state.
  - Filter the results locally using keywords such as community, date, time, or kind mentioned in the user prompt.
  - Prepare summaries that include at minimum the event `id`, `key`, `community`, `dtstart`, `quantity`, and `kind`.
  - If the user references "the last created" or similar, choose the closest match by comparing datetimes.

Return the filtered events so the agent can select identifiers for later API calls.

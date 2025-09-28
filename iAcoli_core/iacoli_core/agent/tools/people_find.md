**Tool: Find People**
Locate existing acolitos or other members before performing updates or assignments.

- **Endpoint:** `GET /api/people`
  - **Payload (optional):**
    - `name`: partial name match; comparison ignores case and accents.
    - `community`: community code such as `MAT` or `DES`.
    - `active`: boolean filter. Accepts true/false style values.
    - `morning`: boolean filter to limit to morning-preferring members.
  - Always review the returned list to pick the correct `id` for follow-up steps.
  - Use `store_result_as` so later calls can reference the selected person (for example, `"store_result_as": "people_list"`).

- **Endpoint:** `GET /api/people/{person_id}`
  - Use the `id` obtained from the list response.
  - Returns the full record, including assignments and availability blocks.
  - Also store the result when you need to reuse specific fields.

Typical flow: list with filters -> select the desired `id` from `store.people_list` -> (optional) fetch details -> perform the update.

**Tool: Update Person**
Adjust the data for an existing acolito/member once you know their identifier.

- **Endpoint:** `PUT /api/people/{person_id}`
  - Replace `{person_id}` with the UUID from the list/detail response.
  - Always include the complete, updated values for any field you touch. For `roles`, send the full list of role codes (see the create tool reference) so nothing is lost.
  - **Payload fields (all optional, omit anything that should remain unchanged):**
    - `name`: updated full name.
    - `community`: community code.
    - `roles`: complete list of role codes the person can perform.
    - `morning`: boolean flag.
    - `active`: boolean flag.
    - `locale`: locale preference such as `pt-BR`.
  - Example sequence (JSON outline):
    ```json
    {
      "response_text": "...",
      "api_calls": [
        {
          "name": "find_fabio",
          "endpoint": "GET /api/people",
          "payload": {"name": "fabio"},
          "store_result_as": "people_list"
        },
        {
          "name": "update_fabio",
          "endpoint": "PUT /api/people/{{people_list[0].id}}",
          "payload": {"roles": ["LIB", "CRU"], "name": "Fabio Miguel"}
        }
      ]
    }
    ```

Typical workflow: find the person (`GET /api/people` with a name filter) -> confirm details if needed (`GET /api/people/{id}`) -> send the update with the desired changes.

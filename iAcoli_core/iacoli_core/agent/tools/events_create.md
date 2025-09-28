**Tool: Create Single Event**
Use to create one calendar event.

- **Endpoint:** `POST /api/events`
- **Payload:**
  - `community` (string, required): community code such as "MAT".
  - `date` (string, required): ISO date formatted as "YYYY-MM-DD".
  - `time` (string, required): 24h time formatted as "HH:MM".
  - `quantity` (integer, required): number of acolytes required.
  - `kind` (string, optional, default "REG"): allowed values are REG, SOLENE, ESPECIAL.
  - `pool` (array of UUID, optional): limit assignments to these person ids.
  - `dtend` (string, optional): ISO datetime for the event end.

When this tool is triggered the orchestrator adds timezone information automatically.
Return the created event object when the call succeeds.

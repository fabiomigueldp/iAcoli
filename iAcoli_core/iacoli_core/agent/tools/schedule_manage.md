**Tool: Manage Schedule**
Use these endpoints to inspect or change the scale (escala) and assignments.

- **GET /api/schedule/lista**: list filled slots. Optional query keys: `periodo`, `de`, `ate`, `communities`, `roles`. Dates must be `YYYY-MM-DD` strings.
- **GET /api/schedule/livres**: list missing assignments for every event. Same optional query keys as `/lista` except `roles`.
- **GET /api/schedule/checagem**: return conflicts or problems in the selected window. Optional query keys: `periodo`, `de`, `ate`, `communities`.
- **GET /api/schedule/estatisticas**: workload stats per person. Same optional query keys as `/checagem`.
- **GET /api/schedule/sugestoes**: ask for best candidates. Required query keys: `event` (event id or key) and `role`. Optional: `top` (default 5) and `seed`.
- **POST /api/schedule/recalcular**: rebuild assignments. Payload keys: `periodo`, `de`, `ate`, `seed` (all optional). Use when the user says "recalcule" or "gere a escala".
- **POST /api/schedule/resetar**: clear assignments inside a period. Payload like the recalc payload.
- **POST /api/schedule/atribuir**: assign someone manually. Payload: `event`, `role`, `person_id` (UUID string).
- **POST /api/schedule/limpar**: remove one assignment. Payload: `event`, `role`.
- **POST /api/schedule/trocar**: swap two assignments. Payload: `event_a`, `role_a`, `event_b`, `role_b`.

Tips:
- Always choose the correct event identifier first (list events or schedule rows, then reuse `id` or `key`).
- Chain calls with placeholders, e.g. `"endpoint": "GET /api/schedule/sugestoes", "payload": {"event": "{{next_mass.id}}", "role": "TUR"}`.
- Combine listing endpoints before mutating so the agent confirms context in multiple steps.

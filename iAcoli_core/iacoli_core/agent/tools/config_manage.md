**Tool: Manage System Configuration**
Inspect or adjust global scheduling parameters.

- **GET /api/config**: retrieve the full configuration (general, fairness, weights, packs).
- **PUT /api/config**: persist new configuration values. Payload structure mirrors the GET response:
  ```json
  {
    "general": {"timezone": "America/Sao_Paulo", ...},
    "fairness": {"fair_window_days": 30, ...},
    "weights": {"load_balance": 1.0, ...},
    "packs": {"4": ["CER1", "CER2", "TUR", "LIB"], ...}
  }
  ```
  Always start from the GET response, tweak the requested fields, and send the complete object back so nothing is dropped.
- **POST /api/config/recarregar**: reload settings from disk (discarding unsaved tweaks).

Flow tip: when the user asks for a single value ("qual e o peso"), read the config and answer without modifying it. For updates, fetch first, adjust fields, then PUT.

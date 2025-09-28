**Tool: Manage System State**
Handle persistence and undo operations at the platform level.

- **POST /api/system/salvar**: save the current state to disk. Payload can include `{"path": "optional/path.json"}` or omit to use the default path. Response returns the file path.
- **POST /api/system/carregar**: load a saved state. Payload must include `{"path": "path/to/state.json"}`. Validate that the user supplied a valid path.
- **POST /api/system/undo**: undo the last mutating command. No payload required. Response contains a human-readable message.

Only run these endpoints when the user explicitly asks to save, load, or undo operations.

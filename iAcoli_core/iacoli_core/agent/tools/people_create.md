**Tool: Create Person**
Register a new person who can receive assignments.

- **Endpoint:** `POST /api/people`
- **Payload:**
  - `name` (string, required): full name.
  - `community` (string, required): community code linked to the person.
  - `roles` (array of string, optional): role codes the person can perform.
  - `morning` (boolean, optional): availability flag for morning events.
  - `active` (boolean, optional, default true): keep false for archived records.
  - `locale` (string, optional): locale preference such as `pt-BR`.

**Role Reference**
Use uppercase codes from this list when filling `roles` (ask for clarification if none are provided):
- `LIB` - Librifero. Aliases: acolito, acolyte, altar server.
- `CRU` - Cruciferario (cross bearer).
- `MIC` - Microfonario (microphone support).
- `TUR` - Turiferario (thurifer).
- `NAV` - Naveteiro (incense boat).
- `CER1` - First ceroferario (candle bearer). Match names such as "acolito 1" or "acolyte 1".
- `CER2` - Second ceroferario (candle bearer). Match names such as "acolito 2" ou "acolyte 2".
- `CAM` - Campanario (bell ringer).

**Nota Importante:** Se o usuário solicitar "todas as funções", "todas as qualificações", "qualificada com todas as funções" ou termos similares, você DEVE preencher o campo `roles` com a lista completa de códigos de função fornecida na seção "CONTEXTO ATUAL DO SISTEMA" do seu prompt. Use todos os códigos disponíveis: `["LIB", "CRU", "MIC", "TUR", "NAV", "CER1", "CER2", "CAM"]`.

Respond with the created person object including the generated `id`.

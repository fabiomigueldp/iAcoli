from __future__ import annotations



from pathlib import Path

from typing import Sequence

import unicodedata



BASE_PROMPT = """

Você é iAcoli, um agente de software cuja única função é traduzir a linguagem natural do usuário em chamadas de API para gerenciar um sistema de escalas litúrgicas.



**AVISO CRÍTICO: SUA PRIMEIRA E ÚNICA LINHA DE RESPOSTA DEVE SER UM JSON VÁLIDO. NÃO ESCREVA NADA ANTES DO JSON.**



**REGRAS CRÍTICAS E INVIOLÁVEIS:**

1.  **SAÍDA ESTRITAMENTE JSON:** Sua resposta DEVE COMEÇAR IMEDIATAMENTE com { e terminar com }. NUNCA inclua texto, explicações, comentários ou formatação markdown (como ```json) antes ou depois do objeto JSON. O JSON deve ser a resposta completa.

2.  **NÃO SEJA UM ASSISTENTE GERAL:** Sua função NÃO é dar conselhos, pesquisar na web ou fornecer informações do mundo real. Você opera um sistema interno. Se o usuário pedir algo fora do escopo das ferramentas fornecidas, sua `response_text` deve ser "Desculpe, só posso realizar ações relacionadas ao gerenciamento de escalas, acólitos e eventos do sistema." com um array `api_calls` vazio.

3.  **USE AS FERRAMENTAS:** Todas as ações devem ser mapeadas para uma ou mais chamadas de API listadas na documentação de ferramentas. Se uma ação não pode ser realizada com as ferramentas, informe a limitação.

4.  **SEJA OBJETIVO:** A `response_text` deve ser uma confirmação curta e direta do que foi (ou será) feito. Ex: "Ok, acólita Maria Clara cadastrada com sucesso." ou "Certo, buscando eventos na comunidade São João Batista...".

5.  **PLANEJE PASSOS:** Para comandos complexos, descreva todas as chamadas necessarias na ordem correta (ex.: localizar > analisar > executar) e busque contexto antes de mutacoes.



**ESQUEMA DE SAÍDA OBRIGATÓRIO:**

{"response_text": "sua mensagem aqui", "api_calls": [suas chamadas de API aqui]}



**EXEMPLO DE RESPOSTA VÁLIDA (COPIE EXATAMENTE ESTE FORMATO):**

{"response_text": "Ok, cadastrando acólita Maria Clara com todas as funções na comunidade São João Batista.", "api_calls": [{"name": "create_person", "endpoint": "POST /api/people", "payload": {"name": "Maria Clara", "community": "SJB", "roles": ["LIB", "CRU", "MIC", "TUR", "NAV", "CER1", "CER2", "CAM"]}}]}



**ATENÇÃO:** Certifique-se de fechar todos os { com } e todos os [ com ]. Conte as chaves e colchetes!



**CONTEXTO ATUAL DO SISTEMA:**

{system_context}



**DOCUMENTAÇÃO DAS FERRAMENTAS DISPONÍVEIS:**

{tool_docs}



LEMBRE-SE: Comece sua resposta IMEDIATAMENTE com { - não escreva nada antes!

"""



TOOLS_DIR = Path(__file__).resolve().parent / "tools"



KEYWORD_MAP: dict[str, list[str]] = {

    "missa": ["events_create.md", "events_manage.md", "schedule_manage.md"],

    "celebracao": ["events_create.md", "events_manage.md", "schedule_manage.md"],

    "celebracao eucaristica": ["events_create.md", "events_manage.md", "schedule_manage.md"],

    "encontro": ["events_create.md", "events_manage.md"],

    "reuniao": ["events_create.md", "events_manage.md"],

    "evento": ["events_create.md", "events_manage.md", "events_find.md"],

    "eventos": ["events_find.md", "events_manage.md"],

    "criar": ["events_create.md", "events_manage.md"],

    "crie": ["events_create.md", "events_manage.md"],

    "agendar": ["events_create.md", "events_manage.md"],

    "agende": ["events_create.md", "events_manage.md"],

    "agendamento": ["events_create.md", "events_manage.md"],

    "remover": ["events_delete.md", "events_find.md", "people_remove.md", "events_manage.md"],

    "deletar": ["events_delete.md", "events_find.md", "people_remove.md", "events_manage.md"],

    "excluir": ["events_delete.md", "events_find.md", "people_remove.md", "events_manage.md"],

    "apagar": ["events_delete.md", "events_find.md", "people_remove.md", "events_manage.md"],

    "triduo": ["series_create.md", "series_manage.md"],

    "serie": ["series_create.md", "series_manage.md"],

    "series": ["series_create.md", "series_manage.md"],

    "recorrencia": ["recurrence_manage.md"],

    "recorrencias": ["recurrence_manage.md"],

    "recorrente": ["recurrence_manage.md"],

    "pessoa": ["people_create.md", "people_find.md", "people_update.md", "people_remove.md", "availability_manage.md"],

    "pessoas": ["people_create.md", "people_find.md", "people_update.md", "people_remove.md", "availability_manage.md"],

    "acolito": ["people_create.md", "people_find.md", "people_update.md", "people_remove.md", "availability_manage.md"],

    "acolitos": ["people_create.md", "people_find.md", "people_update.md", "people_remove.md", "availability_manage.md"],

    "acolyte": ["people_create.md", "people_find.md", "people_update.md", "people_remove.md", "availability_manage.md"],

    "acolytes": ["people_create.md", "people_find.md", "people_update.md", "people_remove.md", "availability_manage.md"],

    "editar": ["people_find.md", "people_update.md", "events_manage.md"],

    "edite": ["people_find.md", "people_update.md", "events_manage.md"],

    "alterar": ["people_find.md", "people_update.md", "events_manage.md"],

    "alteracao": ["people_find.md", "people_update.md", "events_manage.md"],

    "atualizar": ["people_find.md", "people_update.md", "events_manage.md"],

    "atualize": ["people_find.md", "people_update.md", "events_manage.md"],

    "modificar": ["people_find.md", "people_update.md", "events_manage.md"],

    "update": ["people_find.md", "people_update.md", "events_manage.md"],

    "renomear": ["people_find.md", "people_update.md"],

    "renomeie": ["people_find.md", "people_update.md"],

    "nomear": ["people_find.md", "people_update.md"],

    "competencia": ["people_find.md", "people_update.md"],

    "competencias": ["people_find.md", "people_update.md"],

    "cruz": ["people_find.md", "people_update.md"],

    "cruciferario": ["people_find.md", "people_update.md"],

    "indisponivel": ["availability_manage.md", "people_find.md", "schedule_manage.md"],

    "indisponibilidade": ["availability_manage.md", "people_find.md", "schedule_manage.md"],

    "disponibilidade": ["availability_manage.md", "people_find.md", "schedule_manage.md"],

    "bloqueio": ["availability_manage.md", "people_find.md"],

    "bloqueios": ["availability_manage.md", "people_find.md"],

    "bloquear": ["availability_manage.md", "people_find.md"],

    "bloqueie": ["availability_manage.md", "people_find.md"],

    "desbloquear": ["availability_manage.md", "people_find.md"],

    "desbloqueie": ["availability_manage.md", "people_find.md"],

    "ferias": ["availability_manage.md", "schedule_manage.md"],

    "escala": ["schedule_manage.md", "events_manage.md"],

    "recalcular": ["schedule_manage.md"],

    "recalcule": ["schedule_manage.md"],

    "recalculo": ["schedule_manage.md"],

    "gerar": ["schedule_manage.md"],

    "gere": ["schedule_manage.md"],

    "checar": ["schedule_manage.md"],

    "checagem": ["schedule_manage.md"],

    "conflito": ["schedule_manage.md"],

    "conflitos": ["schedule_manage.md"],

    "livre": ["schedule_manage.md", "events_manage.md"],

    "livres": ["schedule_manage.md", "events_manage.md"],

    "sugestao": ["schedule_manage.md"],

    "sugestoes": ["schedule_manage.md"],

    "candidato": ["schedule_manage.md"],

    "candidatos": ["schedule_manage.md"],

    "melhor": ["schedule_manage.md"],

    "melhores": ["schedule_manage.md"],

    "top": ["schedule_manage.md"],

    "configuracao": ["config_manage.md"],

    "configuracoes": ["config_manage.md"],

    "config": ["config_manage.md"],

    "ajuste": ["config_manage.md"],

    "ajustar": ["config_manage.md"],

    "peso": ["config_manage.md"],

    "pesos": ["config_manage.md"],

    "parametro": ["config_manage.md"],

    "parametros": ["config_manage.md"],

    "salvar estado": ["system_manage.md"],

    "carregar estado": ["system_manage.md"],

    "desfazer": ["system_manage.md"],

    "undo": ["system_manage.md"],

    "historico": ["system_manage.md"],

    "pool": ["events_manage.md"],

}



DEFAULT_TOOL_FILES: list[str] = ["events_find.md", "people_find.md", "schedule_manage.md"]





def _normalize(text: str) -> str:

    normalized = unicodedata.normalize("NFKD", text or "")

    return "".join(ch for ch in normalized if ord(ch) < 128).lower()





def _select_tool_files(user_prompt: str) -> list[str]:

    norm_text = _normalize(user_prompt)

    selected: list[str] = []

    for keyword, filenames in KEYWORD_MAP.items():

        if keyword in norm_text:

            selected.extend(filenames)

    if not selected:

        selected.extend(DEFAULT_TOOL_FILES)

    unique: list[str] = []

    for name in selected:

        if name not in unique:

            unique.append(name)

    return unique





def _load_tool_docs(filenames: Sequence[str]) -> str:

    docs: list[str] = []

    for name in filenames:

        path = TOOLS_DIR / name

        if path.exists():

            content = path.read_text(encoding="utf-8").strip()

            if content:

                docs.append(content)

    return "\n\n".join(docs)





def build_system_prompt(user_prompt: str) -> str:

    # Importar ROLE_CODES para incluir no contexto

    from ..models import ROLE_CODES, COMMUNITIES

    

    # 1. Carregar as ferramentas dinamicamente

    tool_filenames = _select_tool_files(user_prompt)

    tool_docs = _load_tool_docs(tool_filenames)

    

    # 2. Construir o contexto do sistema

    all_roles_str = ", ".join(ROLE_CODES)

    all_communities = ", ".join([f"'{code}' ({name})" for code, name in COMMUNITIES.items()])

    system_context = (

        f"- A lista completa de 'roles' (funções) disponíveis no sistema é: [{all_roles_str}].\n"

        f"- As comunidades disponíveis são: {all_communities}.\n"

        f"- O código para a comunidade 'São João Batista' é 'SJB'."

    )

    

    # 3. Formatar o prompt final

    final_prompt = BASE_PROMPT.strip()

    final_prompt = final_prompt.replace("{system_context}", system_context)

    final_prompt = final_prompt.replace("{tool_docs}", tool_docs)

    

    return final_prompt


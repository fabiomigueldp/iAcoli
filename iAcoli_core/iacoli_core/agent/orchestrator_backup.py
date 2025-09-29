from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from urllib.parse import parse_qsl, urlsplit
from typing import Any, Callable, Dict, List, Sequence, Tuple
from uuid import UUID

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - package may be optional locally
    OpenAI = None  # type: ignore[assignment]

from ..config import FairnessConfig, GeneralConfig, WeightConfig
from ..errors import ValidationError
from ..utils import strip_diacritics
from ..webapp.container import ServiceContainer
from .prompt_builder import build_system_prompt, load_all_tool_docs

PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
PATH_PARAM_PATTERN = re.compile(r"{([^{}]+)}")


AGENT_RESPONSE_FORMAT: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "agent_step",
        "schema": {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "action": {
                    "type": ["object", "null"],
                    "properties": {
                        "name": {"type": ["string", "null"]},
                        "endpoint": {
                        "type": "string",
                        "pattern": "^[A-Z]+\\s+/.*$",
                        "description": "Sempre use o formato METHOD /caminho com os endpoints documentados."
                    },
                        "payload": {"type": ["object", "null"]},
                        "store_result_as": {"type": ["string", "null"]}
                    },
                    "required": ["endpoint"],
                    "additionalProperties": False
                },
                "final_answer": {"type": ["string", "null"]},
                "response_text": {"type": ["string", "null"]}
            },
            "required": ["thought"],
            "additionalProperties": False
        }
    }
}



def _to_json(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False)
    except TypeError:
        return str(data)

@dataclass(slots=True)
class EndpointHandler:
    method: str
    template: str
    func: Callable[..., Any]
    expect_payload: bool = True
    expect_query: bool = False
    param_names: list[str] = field(init=False)
    regex: re.Pattern[str] = field(init=False)

    def __post_init__(self) -> None:
        self.method = self.method.upper()
        self.param_names: list[str] = PATH_PARAM_PATTERN.findall(self.template)
        self.regex = self._compile_regex(self.template)

    def match(self, path: str) -> dict[str, str] | None:
        if path == self.template:
            return {}
        match = self.regex.match(path)
        if not match:
            return None
        return {key: value for key, value in match.groupdict().items() if value is not None}

    @staticmethod
    def _compile_regex(template: str) -> re.Pattern[str]:
        parts: list[str] = []
        cursor = 0
        for match in PATH_PARAM_PATTERN.finditer(template):
            start, end = match.span()
            parts.append(re.escape(template[cursor:start]))
            name = match.group(1)
            parts.append(f"(?P<{name}>[^/]+)")
            cursor = end
        parts.append(re.escape(template[cursor:]))
        pattern = "^" + "".join(parts) + "$"
        return re.compile(pattern)


class AgentOrchestrator:
    """Coordinates LLM guidance with direct calls into the core service."""

    def __init__(self, container: ServiceContainer) -> None:
        self.container = container
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)  # Força nivel DEBUG para transparencia total
        self.max_iterations = 8
        self.logger.info("=== ORCHESTRATOR INICIALIZADO ===")
        self.logger.info("Container: %s", container)
        self.logger.info("Max iterations: %s", self.max_iterations)
        # Map endpoints to orchestrator handlers
        self._handlers: list[EndpointHandler] = []
        self._register_endpoint("POST", "/api/events", self._create_event)
        self._register_endpoint("GET", "/api/events", self._list_events)
        self._register_endpoint("GET", "/api/events/{identifier}", self._get_event_detail, expect_payload=False)
        self._register_endpoint("PUT", "/api/events/{identifier}", self._update_event)
        self._register_endpoint("DELETE", "/api/events/{identifier}", self._delete_event, expect_payload=False)
        self._register_endpoint("GET", "/api/events/{identifier}/pool", self._get_event_pool, expect_payload=False)
        self._register_endpoint("POST", "/api/events/{identifier}/pool", self._set_event_pool)
        self._register_endpoint("DELETE", "/api/events/{identifier}/pool", self._clear_event_pool, expect_payload=False)

        self._register_endpoint("POST", "/api/series", self._create_series)
        self._register_endpoint("GET", "/api/series", self._list_series, expect_payload=False)
        self._register_endpoint("PATCH", "/api/series/{series_id}", self._update_series)
        self._register_endpoint("DELETE", "/api/series/{series_id}", self._delete_series, expect_payload=False)

        self._register_endpoint("GET", "/api/series/recorrencias", self._list_recurrences, expect_payload=False)
        self._register_endpoint("POST", "/api/series/recorrencias", self._create_recurrence)
        self._register_endpoint("PATCH", "/api/series/recorrencias/{recurrence_id}", self._update_recurrence)
        self._register_endpoint("DELETE", "/api/series/recorrencias/{recurrence_id}", self._delete_recurrence, expect_payload=False)

        self._register_endpoint("POST", "/api/people", self._create_person)
        self._register_endpoint("GET", "/api/people", self._list_people)
        self._register_endpoint("GET", "/api/people/{identifier}", self._get_person, expect_payload=False)
        self._register_endpoint("PUT", "/api/people/{identifier}", self._update_person)
        self._register_endpoint("PATCH", "/api/people/{identifier}", self._update_person)
        self._register_endpoint("DELETE", "/api/people/{identifier}", self._delete_person, expect_payload=False)
        self._register_endpoint("GET", "/api/people/{person_id}/blocks", self._list_person_blocks, expect_payload=False)
        self._register_endpoint("POST", "/api/people/{person_id}/blocks", self._add_person_block)
        self._register_endpoint("DELETE", "/api/people/{person_id}/blocks", self._remove_person_block, expect_payload=True, expect_query=True)

        self._register_endpoint("GET", "/api/schedule/lista", self._schedule_list)
        self._register_endpoint("GET", "/api/schedule/livres", self._schedule_free)
        self._register_endpoint("GET", "/api/schedule/checagem", self._schedule_check)
        self._register_endpoint("GET", "/api/schedule/estatisticas", self._schedule_stats)
        self._register_endpoint("GET", "/api/schedule/sugestoes", self._schedule_suggestions)
        self._register_endpoint("GET", "/api/schedule/suggestions", self._schedule_suggestions)
        self._register_endpoint("POST", "/api/schedule/recalcular", self._schedule_recalculate)
        self._register_endpoint("POST", "/api/schedule/recalculate", self._schedule_recalculate)
        self._register_endpoint("POST", "/api/schedule/resetar", self._schedule_reset)
        self._register_endpoint("POST", "/api/schedule/assignments/apply", self._schedule_apply_assignment)
        self._register_endpoint("POST", "/api/schedule/atribuir", self._schedule_apply_assignment)
        self._register_endpoint("POST", "/api/schedule/assignments/clear", self._schedule_clear_assignment)
        self._register_endpoint("POST", "/api/schedule/limpar", self._schedule_clear_assignment)
        self._register_endpoint("POST", "/api/schedule/trocar", self._schedule_swap_assignments)

        self._register_endpoint("GET", "/api/config", self._get_config, expect_payload=False)
        self._register_endpoint("PUT", "/api/config", self._update_config)
        self._register_endpoint("POST", "/api/config/recarregar", self._reload_config, expect_payload=False)

        self._register_endpoint("POST", "/api/system/salvar", self._save_state)
        self._register_endpoint("POST", "/api/system/carregar", self._load_state)
        self._register_endpoint("POST", "/api/system/undo", self._undo_last, expect_payload=False)

    def _register_endpoint(
        self,
        method: str,
        template: str,
        handler: Callable[..., Any],
        *,
        expect_payload: bool = True,
        expect_query: bool = False,
    ) -> None:
        self._handlers.append(EndpointHandler(method, template, handler, expect_payload, expect_query))



    def interact(self, user_prompt: str) -> Dict[str, Any]:
        # Resposta direta para perguntas simples sobre dados
        direct_response = self._try_direct_response(user_prompt)
        if direct_response:
            return direct_response
            
        dynamic_context = self._build_dynamic_context_snapshot()
        tool_docs = load_all_tool_docs()
        system_prompt = build_system_prompt(
            user_prompt,
            dynamic_context=dynamic_context,
            tool_docs=tool_docs,
        )

        stored_results: Dict[str, Any] = {}
        scratchpad: list[dict[str, str]] = []
        executed_actions: List[Dict[str, Any]] = []
        final_answer: str | None = None

        self.logger.info("=== NOVA INTERACAO INICIADA ===")
        self.logger.info("[Agent] User prompt: %s", user_prompt)
        self.logger.info("[Agent] Resumo dinamico: %s", dynamic_context.replace('\n', ' | '))
        self.logger.info("[Agent] System prompt length: %d chars", len(system_prompt))

        # Verificação direta para perguntas simples sobre dados existentes
        direct_answer = self._try_direct_answer(user_prompt, dynamic_context)
        if direct_answer:
            self.logger.info("[Agent] Resposta direta encontrada, evitando chamada LLM")
            final_answer = direct_answer
            executed_actions = []
            
            return {
                "response_text": final_answer,
                "executed_actions": executed_actions,
            }
        
        # Primeira tentativa: resposta direta via LLM
        # Para perguntas sobre dados, inclui contexto diretamente na mensagem do usuário
        enhanced_user_prompt = user_prompt
        if any(word in user_prompt.lower() for word in ["quantos", "quais", "nomes", "eventos", "próximo", "lista", "dados"]):
            enhanced_user_prompt = f"{user_prompt}\n\nCONTEXTO ATUAL DO SISTEMA:\n{dynamic_context}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": enhanced_user_prompt},
        ]
        
        self.logger.debug("[Agent] Enhanced user prompt: %s", enhanced_user_prompt[:500] + "..." if len(enhanced_user_prompt) > 500 else enhanced_user_prompt)
        
        for step in range(1, self.max_iterations + 1):
            self.logger.info("=== ITERACAO %d/%d ===", step, self.max_iterations)
            
            parsed, llm_error = self._call_llm(messages)
            if parsed is None:
                self.logger.error("[Agent] Falha na comunicação: %s", llm_error)
                final_answer = f"Erro na comunicação com o sistema: {llm_error}"
                break

            self.logger.info("[Agent] Resposta LLM: %s", _to_json(parsed))
            
            thought = str(parsed.get("thought") or "").strip()
            final_candidate = parsed.get("final_answer") or parsed.get("response_text")
            action_payload = parsed.get("action")
            
            # Executa ação se presente
            if isinstance(action_payload, dict) and action_payload:
                entry, observation = self._execute_react_action(action_payload, stored_results)
                executed_actions.append(entry)
                
                # Se tem resposta final, termina aqui mesmo executando a ação
                if isinstance(final_candidate, str) and final_candidate.strip():
                    final_answer = final_candidate.strip()
                    self.logger.info("[Agent] Resposta final + ação executada, finalizando")
                    break
                
                # Só continua iterando se não há resposta final E a ação foi bem-sucedida
                # (precisa de mais informações)
                if entry.get("status") == "success" and not final_candidate:
                    self.logger.info("[Agent] Ação executada, continuando para obter resposta final")
                    # Prepara contexto para próxima iteração
                    context_summary = f"Ação executada: {self._summarize_action(action_payload, entry)}\nObservação: {observation}"
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"{user_prompt}\n\nContexto da execução anterior:\n{context_summary}\n\nAgora forneça a resposta final ao usuário."},
                    ]
                    continue
                else:
                    # Erro ou já tem resposta final
                    final_answer = final_candidate or f"Erro ao executar: {entry.get('error', 'desconhecido')}"
                    break
            else:
                # Sem ação, deve ter resposta final
                final_answer = final_candidate or "Resposta não fornecida pelo agente."
                self.logger.info("[Agent] Resposta direta sem ação")
                break

        if final_answer is None:
            error_entry = next((item for item in reversed(executed_actions) if item.get("status") in {"validation_error", "error"}), None)
            if error_entry:
                final_answer = f"Desculpe, ocorreu um erro ao executar as acoes: {error_entry.get('error', 'sem detalhes')}"
            elif executed_actions:
                final_answer = "Tudo certo, acoes executadas."
            elif scratchpad:
                final_answer = "Desculpe, tive dificuldades para gerar uma resposta valida. Vamos tentar novamente."
            else:
                final_answer = "Desculpe, nao consegui processar seu pedido agora."

        self.logger.info("=== INTERACAO CONCLUIDA ===")
        self.logger.info("[Agent] Total de iterações: %d", step)
        self.logger.info("[Agent] Resposta final: %s", final_answer)
        self.logger.info("[Agent] Total de ações executadas: %d", len(executed_actions))
        self.logger.info("[Agent] Ações executadas: %s", _to_json(executed_actions))
        
        result = {
            "response_text": final_answer,
            "executed_actions": executed_actions,
        }
        self.logger.debug("[Agent] Resultado completo: %s", _to_json(result))
        
        return result

    def _try_direct_answer(self, user_prompt: str, dynamic_context: str) -> str | None:
        """Tenta responder diretamente usando o contexto, sem chamar o LLM para queries simples."""
        prompt_lower = user_prompt.lower()
        
        # Extrai números do contexto dinâmico
        people_count = None
        events_count = None
        
        # Procura por "Pessoas registradas: X"
        import re
        people_match = re.search(r'pessoas registradas:\s*(\d+)', dynamic_context.lower())
        if people_match:
            people_count = int(people_match.group(1))
        
        # Procura por "Eventos agendados: X"
        events_match = re.search(r'eventos agendados:\s*(\d+)', dynamic_context.lower())
        if events_match:
            events_count = int(events_match.group(1))
        
        # Responde perguntas sobre quantidade de pessoas/acólitos
        if any(word in prompt_lower for word in ["quantas pessoas", "quantos acólitos", "quantos acolitos", "quantidade de pessoas", "pessoas registradas"]):
            if people_count is not None:
                return f"Temos {people_count} pessoas registradas no sistema atualmente."
        
        # Responde perguntas sobre eventos
        if any(word in prompt_lower for word in ["quantos eventos", "eventos agendados", "quantidade de eventos"]):
            if events_count is not None:
                return f"Temos {events_count} eventos agendados no sistema."
        
        # Lista nomes das pessoas (extrai do contexto detalhado)
        if any(word in prompt_lower for word in ["quais são os nomes", "nomes dos acólitos", "nomes das pessoas", "lista de pessoas"]):
            # Extrai nomes das pessoas do contexto
            names = []
            lines = dynamic_context.split('|')
            for line in lines:
                line = line.strip()
                if '(id=' in line and 'ativo)' in line:
                    # Extrai o nome antes do primeiro parêntese
                    name_part = line.split('(id=')[0].strip()
                    if name_part.startswith('-'):
                        name_part = name_part[1:].strip()
                    names.append(name_part)
            
            if names:
                if len(names) == 1:
                    return f"Temos 1 pessoa registrada: {names[0]}."
                else:
                    names_str = ", ".join(names[:-1]) + f" e {names[-1]}"
                    return f"Temos {len(names)} pessoas registradas: {names_str}."
        
        # Não conseguiu responder diretamente
        return None

    def _call_llm(self, messages: List[Dict[str, str]]) -> Tuple[Dict[str, Any] | None, str | None]:
        self.logger.info("[LLM] Iniciando chamada para LLM")
        
        if OpenAI is None:
            error = "openai package not installed. Cannot reach Perplexity Sonar."
            self.logger.error("[LLM] %s", error)
            return None, error

        api_key = os.environ.get("PPLX_API_KEY")
        if not api_key:
            error = "Missing PPLX_API_KEY environment variable."
            self.logger.error("[LLM] %s", error)
            return None, error

        self.logger.info("[LLM] API key found, configurando cliente Perplexity")
        client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
        
        try:
            self.logger.info("[LLM] Enviando request para Perplexity Sonar com modelo 'sonar'")
            self.logger.debug("[LLM] Response format: %s", AGENT_RESPONSE_FORMAT)
            
            response = client.chat.completions.create(
                model="sonar",
                messages=messages,
                response_format=AGENT_RESPONSE_FORMAT,
                extra_body={"disable_search": True},
                max_tokens=2500,  # Suficiente para respostas completas sem truncar JSON
                temperature=0.1,  # Reduz variabilidade
            )
            
            self.logger.info("[LLM] Response recebido com sucesso")
            self.logger.debug("[LLM] Raw response: %s", response)
            
        except Exception as exc:  # pragma: no cover - network call
            error = f"Failed to call Perplexity Sonar: {exc}"
            self.logger.exception("[LLM] %s", error)
            return None, error

        if not response.choices:
            error = "LLM response has no choices."
            self.logger.error("[LLM] %s", error)
            return None, error

        message = response.choices[0].message
        if message is None or not message.content:
            error = "LLM response message is empty."
            self.logger.error("[LLM] %s", error)
            return None, error

        self.logger.info("[LLM] Processando resposta do LLM")
        
        # Validação prévia da resposta
        content = message.content.strip()
        if not content:
            error = "LLM response is empty"
            self.logger.error("[LLM] %s", error)
            return None, error
            
        # Detecta resposta com lixo repetitivo
        if len(content) > 5000:
            self.logger.warning("[LLM] Resposta muito longa (%d chars), verificando padrões", len(content))
            # Detecta padrões repetitivos mais sofisticadamente
            # Verifica diferentes tipos de padrões comuns
            repetitive_patterns = [
                'URL', 'RLURL', 'AOLITOS', 'ROLESAND', 'INFORMATIONAL',
                'FORBETTERUNDERSTANDING', 'ANDPARTICIPATION'
            ]
            
            for pattern in repetitive_patterns:
                if pattern in content and content.count(pattern) > 5:
                    error = f"LLM response contains repetitive garbage pattern '{pattern}'. Length: {len(content)}"
                    self.logger.error("[LLM] %s", error)
                    return None, error
                    
            # Verifica repetição de substring genérica
            sample = content[:100]
            if len(sample) > 10 and content.count(sample[:10]) > 10:
                error = f"LLM response contains repetitive garbage. Length: {len(content)}"
                self.logger.error("[LLM] %s", error)
                return None, error
        
        self.logger.debug("[LLM] Raw message content: %s", content[:500] + "..." if len(content) > 500 else content)

        try:
            # Primeira tentativa: parsing direto (caso ideal - JSON limpo)
            self.logger.debug("[LLM] Tentando parsing direto do JSON")
            parsed = json.loads(content)
            self.logger.info("[LLM] JSON parseado com sucesso (parsing direto)")
            return parsed, None
        except json.JSONDecodeError:
            self.logger.warning("[LLM] Parsing direto falhou, tentando métodos de recuperação")
            # Segunda tentativa: encontrar JSON válido com múltiplas estratégias
            try:
                # Estratégia 1: Contador de chaves robusto
                start_idx = content.find('{')
                if start_idx == -1:
                    raise json.JSONDecodeError("Nenhum objeto JSON encontrado na resposta.", content, 0)
                
                # Conta chaves balanceadas, lidando com strings e escape
                brace_count = 0
                in_string = False
                escape_next = False
                end_idx = None
                
                for i, char in enumerate(content[start_idx:], start_idx):
                    if escape_next:
                        escape_next = False
                        continue
                    if char == '\\' and in_string:
                        escape_next = True
                        continue
                    if char == '"':
                        in_string = not in_string
                        continue
                    if not in_string:
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                end_idx = i + 1
                                break
                
                if end_idx is not None:
                    json_substring = content[start_idx:end_idx]
                    self.logger.debug("[LLM] Tentativa 1 - JSON extraído: %s", json_substring[:200] + "..." if len(json_substring) > 200 else json_substring)
                    parsed_json = json.loads(json_substring)
                    self.logger.info("[LLM] JSON extraído com sucesso (contador de chaves)")
                    return parsed_json, None
                
                # Estratégia 2: Procurar por padrões conhecidos e truncar
                self.logger.debug("[LLM] Tentativa 2 - Procurando padrões conhecidos")
                
                # Procura por final_answer ou response_text para inferir onde o JSON deveria terminar
                patterns = ['"final_answer":', '"response_text":']
                for pattern in patterns:
                    pattern_idx = content.find(pattern, start_idx)
                    if pattern_idx != -1:
                        # Procura o final dessa string
                        quote_start = content.find('"', pattern_idx + len(pattern))
                        if quote_start != -1:
                            quote_end = content.find('"', quote_start + 1)
                            if quote_end != -1:
                                # Adiciona } } para fechar action e objeto principal
                                reconstructed = content[start_idx:quote_end + 1] + "}}"
                                try:
                                    parsed_json = json.loads(reconstructed)
                                    self.logger.info("[LLM] JSON reconstruído com sucesso usando padrão %s", pattern)
                                    return parsed_json, None
                                except json.JSONDecodeError:
                                    continue
                
                # Estratégia 3: Truncar no primeiro sinal de lixo repetitivo
                self.logger.debug("[LLM] Tentativa 3 - Detectando lixo repetitivo")
                clean_content = content[start_idx:]
                
                # Lista de padrões de lixo conhecidos
                garbage_patterns = ['URL', 'RLURL', 'AOLITOS', 'ROLESAND', 'INFORMATIONAL']
                
                for i in range(100, min(len(clean_content), 2000), 50):
                    chunk = clean_content[:i]
                    
                    # Verifica se há padrões repetitivos
                    for pattern in garbage_patterns:
                        if pattern in chunk and chunk.count(pattern) > 3:
                            # Encontra o início do lixo
                            garbage_start = chunk.find(pattern)
                            before_garbage = clean_content[:garbage_start] + '"}}'
                            try:
                                parsed_json = json.loads(before_garbage)
                                self.logger.info("[LLM] JSON reconstruído removendo lixo repetitivo (%s)", pattern)
                                return parsed_json, None
                            except json.JSONDecodeError:
                                continue
                
                raise json.JSONDecodeError("Todas as estratégias de recuperação falharam.", content, start_idx)
                
            except (json.JSONDecodeError, IndexError) as exc:
                # Apenas se a substring também falhar, então é genuinamente malformado
                truncated = message.content[:300]
                error = f"LLM response is not valid JSON: {exc}. Raw: {truncated!r}"
                self.logger.error("[LLM] %s", error)
                return None, error

    def _build_dynamic_context_snapshot(self) -> str:
        def gather() -> Dict[str, Any]:
            service = self.container.service
            people = service.list_people()
            events = sorted(service.list_events(), key=lambda item: item.dtstart)
            assignments_total = sum(len(mapping) for mapping in service.state.assignments.values())
            series_total = len(service.state.series)

            people_snapshot = [
                {
                    "id": str(person.id),
                    "name": person.name,
                    "community": person.community,
                    "roles": sorted(person.roles),
                    "active": person.active,
                }
                for person in people
            ]

            event_snapshot: List[Dict[str, Any]] = []
            for event in events:
                key_getter = getattr(event, "key", None)
                event_key = None
                if callable(key_getter):
                    try:
                        event_key = key_getter()
                    except Exception:  # pragma: no cover - best effort only
                        event_key = None
                event_snapshot.append(
                    {
                        "id": str(event.id),
                        "key": event_key,
                        "community": event.community,
                        "dtstart": event.dtstart.isoformat(),
                        "kind": event.kind,
                    }
                )

            return {
                "people": people_snapshot,
                "events": event_snapshot,
                "assignments_total": assignments_total,
                "series_total": series_total,
            }

        snapshot = self.container.read(gather)
        people_snapshot: List[Dict[str, Any]] = snapshot.get("people", [])  # type: ignore[assignment]
        events_snapshot: List[Dict[str, Any]] = snapshot.get("events", [])  # type: ignore[assignment]
        lines: List[str] = [
            "Resumo dinamico do estado atual:",
            f"- Pessoas registradas: {len(people_snapshot)}",
            f"- Eventos agendados: {len(events_snapshot)}",
            f"- Series ativas: {snapshot.get('series_total', 0)}",
            f"- Atribuicoes registradas: {snapshot.get('assignments_total', 0)}",
        ]

        if people_snapshot:
            limit_people = 8
            lines.append(f"- Pessoas detalhadas (ate {limit_people}):")
            for person in people_snapshot[:limit_people]:
                roles = ", ".join(person.get("roles", [])) or "sem funcoes"
                status = "ativo" if person.get("active") else "inativo"
                lines.append(
                    f"  - {person.get('name', 'desconhecido')} (id={person.get('id')}, comunidade={person.get('community')}, roles=[{roles}], {status})"
                )
            remaining = len(people_snapshot) - limit_people
            if remaining > 0:
                lines.append(f"  - ... {remaining} pessoas adicionais")
        else:
            lines.append("- Nenhuma pessoa cadastrada.")

        if events_snapshot:
            limit_events = 5
            lines.append(f"- Proximos eventos (ate {limit_events}):")
            for event in events_snapshot[:limit_events]:
                label = f"{event.get('dtstart')} | {event.get('community')} | {event.get('kind')}"
                if event.get("key"):
                    label += f" | key={event.get('key')}"
                label += f" | id={event.get('id')}"
                lines.append(f"  - {label}")
            remaining_events = len(events_snapshot) - limit_events
            if remaining_events > 0:
                lines.append(f"  - ... {remaining_events} eventos adicionais")
        else:
            lines.append("- Nenhum evento agendado.")

        return "\n".join(lines)

    def _optimize_system_prompt(self, system_prompt: str, user_prompt: str) -> str:
        """Otimiza o system prompt removendo documentação desnecessária para a query."""
        self.logger.info("[Agent] Otimizando system prompt para pergunta: %s", user_prompt[:50])
        
        # Para perguntas simples sobre listagem, mante apenas tools básicos
        simple_queries = ["quant", "list", "acolit", "pessoa", "registrad"]
        if any(word in user_prompt.lower() for word in simple_queries):
            # Mantém apenas people_find.md e people_create.md
            lines = system_prompt.split('\n')
            filtered_lines = []
            skip_section = False
            
            for line in lines:
                if line.startswith('=== ') and line.endswith(' ==='):
                    section_name = line.replace('=== ', '').replace(' ===', '')
                    # Mantém apenas seções essenciais
                    skip_section = section_name not in ['people_find.md', 'people_create.md', 'people_update.md']
                    
                if not skip_section:
                    filtered_lines.append(line)
            
            optimized = '\n'.join(filtered_lines)
            self.logger.info("[Agent] Prompt otimizado de %d para %d chars", len(system_prompt), len(optimized))
            return optimized
        
        return system_prompt

    def _try_direct_response(self, user_prompt: str) -> Dict[str, Any] | None:
        """Responde diretamente para perguntas simples sobre dados sem chamar LLM"""
        prompt_lower = user_prompt.lower()
        
        # Perguntas sobre quantidade de acólitos/pessoas
        if any(word in prompt_lower for word in ["quantos acólitos", "quantas pessoas", "quantos acolitos"]):
            summary = self._build_dynamic_context_snapshot()
            
            # Extrai número de pessoas do contexto
            if "pessoas registradas:" in summary.lower():
                lines = summary.split('\n')
                for line in lines:
                    if "pessoas registradas:" in line.lower():
                        try:
                            number = line.split(':')[1].strip()
                            return {
                                "response_text": f"Temos {number} acólitos registrados no sistema.",
                                "executed_actions": []
                            }
                        except:
                            pass
                            
        # Perguntas sobre eventos
        elif any(word in prompt_lower for word in ["quantos eventos", "eventos agendados"]):
            summary = self._build_dynamic_context_snapshot()
            
            if "eventos agendados:" in summary.lower():
                lines = summary.split('\n')
                for line in lines:
                    if "eventos agendados:" in line.lower():
                        try:
                            number = line.split(':')[1].strip()
                            return {
                                "response_text": f"Temos {number} eventos agendados no sistema.",
                                "executed_actions": []
                            }
                        except:
                            pass
                            
        # Perguntas sobre nomes dos acólitos
        elif any(word in prompt_lower for word in ["nomes dos acólitos", "quais são os acólitos", "lista de acólitos", "liste todos acólitos", "liste todos os acólitos", "todos os acólitos", "quem são os acólitos", "quembsao os acolitos", "quem sao os acolitos"]):
            summary = self._build_dynamic_context_snapshot()
            
            # Extrai nomes do contexto
            names = []
            lines = summary.split('\n')
            in_people_section = False
            
            for line in lines:
                if "pessoas detalhadas" in line.lower():
                    in_people_section = True
                    continue
                elif in_people_section and "proximos eventos" in line.lower():
                    # Chegou na seção de eventos, parar
                    break
                elif in_people_section and line.strip().startswith('- '):
                    # Linha como "- Emanuelly (id=..., comunidade=..., ativo)"
                    name_part = line.strip()[2:].split('(')[0].strip()
                    names.append(name_part)
                    
            if names:
                names_str = ', '.join(names)
                return {
                    "response_text": f"Os acólitos registrados são: {names_str}.",
                    "executed_actions": []
                }
        
        return None  # Não é uma pergunta simples, usar LLM normal

    def _render_iteration_prompt(self, user_prompt: str, scratchpad: List[dict[str, str]], step: int) -> str:
        lines: List[str] = [
            "**Objetivo do usuario:**",
            (user_prompt or "(vazio)").strip(),
            "",
            f"**Iteracao atual:** {step}/{self.max_iterations}",
            "",
            "**Historico do agente:**",
        ]

        if not scratchpad:
            lines.append("Nenhuma acao executada ate o momento.")
        else:
            for idx, entry in enumerate(scratchpad, 1):
                lines.append(f"Passo {idx}:")
                thought = entry.get("thought")
                if thought:
                    lines.append(f"- Thought: {thought}")
                action = entry.get("action")
                if action:
                    lines.append(f"- Action: {action}")
                observation = entry.get("observation")
                if observation:
                    lines.append(f"- Observation: {observation}")
                lines.append("")
            if lines and lines[-1] == "":
                lines.pop()

        lines.append("")
        lines.append("Responda com o JSON solicitado no system prompt seguindo o ciclo pensar -> agir -> observar.")
        lines.append("Use apenas endpoints documentados, por exemplo `GET /api/people` para listar acolit@s.")
        return "\n".join(lines).strip()

    def _execute_react_action(self, action: Dict[str, Any], stored_results: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        self.logger.info("=== EXECUTANDO ACTION ===")
        self.logger.info("[Action] Detalhes da action: %s", _to_json(action))
        self.logger.info("[Action] Stored results disponíveis: %s", list(stored_results.keys()))
        
        entry: Dict[str, Any] = {
            "name": action.get("name"),
            "endpoint": action.get("endpoint"),
            "status": "noop",
        }
        store_key = action.get("store_result_as") or action.get("name")
        if store_key:
            entry["store_result_as"] = store_key
            self.logger.info("[Action] Resultado será armazenado como: %s", store_key)

        endpoint_raw = action.get("endpoint")
        if not isinstance(endpoint_raw, str) or not endpoint_raw.strip():
            entry.update({"status": "error", "error": "Endpoint ausente na action."})
            self.logger.error("[Action] Action sem endpoint válido: %s", _to_json(action))
            return entry, self._format_observation(entry)

        try:
            resolved_endpoint = self._resolve_endpoint(endpoint_raw, stored_results)
        except Exception as exc:
            entry.update({"status": "error", "error": str(exc)})
            self.logger.error("[Agent] Falha ao resolver endpoint %s: %s", endpoint_raw, exc)
            return entry, self._format_observation(entry)

        entry["endpoint"] = resolved_endpoint
        self.logger.info("[Action] Endpoint resolvido: %s", resolved_endpoint)
        self.logger.info("[Action] Executando action=%s endpoint=%s", entry.get("name"), resolved_endpoint)
        self.logger.debug("[Action] Payload original: %s", _to_json(action.get("payload")))

        try:
            cleaned_payload = self._ensure_dict(action.get("payload"))
            self.logger.debug("[Action] Payload limpo: %s", _to_json(cleaned_payload))
            resolved_payload = self._resolve_placeholders(cleaned_payload, stored_results)
            self.logger.info("[Action] Payload com placeholders resolvidos: %s", _to_json(resolved_payload))
        except Exception as exc:
            entry.update({"status": "error", "error": f"Erro ao preparar payload: {exc}"})
            self.logger.error("[Action] Falha ao preparar payload para %s: %s", resolved_endpoint, exc)
            return entry, self._format_observation(entry)

        try:
            self.logger.info("[Action] Iniciando dispatch para: %s", resolved_endpoint)
            result = self._dispatch(resolved_endpoint, resolved_payload)
            self.logger.info("[Action] Dispatch concluído com sucesso")
            self.logger.debug("[Action] Resultado bruto: %s", _to_json(result))
            
            serializable = self._to_serializable(result)
            self.logger.debug("[Action] Resultado serializado: %s", _to_json(serializable))
            
            if store_key:
                stored_results[str(store_key)] = serializable
                self.logger.info("[Action] Resultado armazenado em stored_results['%s']", store_key)
            
            entry.update({
                "status": "success",
                "payload": resolved_payload,
                "result": serializable,
            })
            self.logger.info("[Action] Action %s concluída com SUCESSO", entry.get("name"))
            
        except ValidationError as exc:
            entry.update({
                "status": "validation_error",
                "error": str(exc),
                "payload": resolved_payload,
            })
            self.logger.warning("[Action] ERRO DE VALIDAÇÃO para %s: %s", resolved_endpoint, exc)
            
        except Exception as exc:  # pragma: no cover - safety net
            self.logger.exception("[Action] ERRO GERAL executando %s: %s", resolved_endpoint, exc)
            entry.update({
                "status": "error",
                "error": str(exc),
                "payload": resolved_payload,
            })

        return entry, self._format_observation(entry)

    def _summarize_action(self, action: Dict[str, Any] | None, entry: Dict[str, Any] | None) -> str:
        if entry:
            endpoint = entry.get("endpoint") or (action.get("endpoint") if action else "<sem endpoint>")
            status = entry.get("status", "noop")
            name = entry.get("name") or (action.get("name") if action else None)
            summary = f"{endpoint} [{status}]" if endpoint else f"[{status}]"
            if name:
                summary = f"{name}: {summary}"
            store_alias = entry.get("store_result_as")
            if store_alias:
                summary += f" (store={store_alias})"
            return summary

        if action:
            endpoint = action.get("endpoint") or "<sem endpoint>"
            name = action.get("name")
            summary = endpoint
            if name:
                summary = f"{name}: {summary}"
            return summary

        return "Nenhuma acao executada nesta iteracao."

    def _format_observation(self, entry: Dict[str, Any]) -> str:
        status = entry.get("status", "unknown")
        endpoint = entry.get("endpoint", "unknown")
        
        if status == "success":
            result = entry.get("result")
            if result is not None:
                # Para listagens simples, mostre apenas count
                if isinstance(result, list):
                    return f"SUCESSO {endpoint}: retornou {len(result)} items. Use os dados para responder."
                # Para resultados únicos, resumo breve
                elif isinstance(result, dict):
                    return f"SUCESSO {endpoint}: dados obtidos. Use para responder."
                else:
                    return f"SUCESSO {endpoint}: {str(result)[:100]}"
            return f"SUCESSO {endpoint}"
        elif status == "error":
            error_msg = entry.get("error", "erro desconhecido")[:150]
            return f"ERRO {endpoint}: {error_msg}"
        elif status == "validation_error":
            error_msg = entry.get("error", "erro de validação")[:150]
            return f"VALIDAÇÃO {endpoint}: {error_msg}"
        else:
            return f"STATUS {status} para {endpoint}"

    def _summarize_json(self, data: Any, *, max_length: int = 800) -> str:
        serializable = self._to_serializable(data)
        try:
            text = json.dumps(serializable, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = json.dumps(str(serializable), ensure_ascii=False)
        if len(text) > max_length:
            return text[: max_length - 3] + "..."
        return text
    def _execute_calls(self, api_calls: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        executed: List[Dict[str, Any]] = []
        stored_results: Dict[str, Any] = {}

        for call in api_calls:
            endpoint = call.get("endpoint")
            alias = call.get("store_result_as")
            payload = call.get("payload")
            name = call.get("name")
            resolved_endpoint = self._resolve_endpoint(endpoint, stored_results) if endpoint else endpoint
            entry: Dict[str, Any] = {
                "name": name,
                "endpoint": resolved_endpoint,
                "status": "noop",
            }
            executed.append(entry)

            cleaned_payload: Dict[str, Any] | None = None
            try:
                cleaned_payload = self._ensure_dict(payload)
                resolved_payload = self._resolve_placeholders(cleaned_payload, stored_results)
                result = self._dispatch(resolved_endpoint, resolved_payload)
                serializable = self._to_serializable(result)
                store_key = alias or name
                if store_key:
                    stored_results[str(store_key)] = serializable
                entry.update({
                    "status": "success",
                    "payload": resolved_payload,
                    "result": serializable,
                })
            except ValidationError as exc:
                entry.update({
                    "status": "validation_error",
                    "error": str(exc),
                    "payload": cleaned_payload or {},
                })
                break
            except Exception as exc:  # pragma: no cover - safety net
                self.logger.exception("Error executing agent call %s: %s", endpoint, exc)
                entry.update({
                    "status": "error",
                    "error": str(exc),
                })
                if cleaned_payload is not None:
                    entry.setdefault("payload", cleaned_payload)
                break

        return executed

    def _dispatch(self, endpoint: Any, payload: Dict[str, Any]) -> Any:
        self.logger.info("[Dispatch] Iniciando dispatch para endpoint: %s", endpoint)
        self.logger.debug("[Dispatch] Payload recebido: %s", _to_json(payload))
        
        if not isinstance(endpoint, str):
            raise ValueError("Endpoint deve ser uma string no formato 'METHOD /path'.")

        parts = endpoint.strip().split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Formato de endpoint invalido: {endpoint}")

        method, raw_path = parts[0].upper(), parts[1]
        self.logger.info("[Dispatch] Method: %s, Path: %s", method, raw_path)
        
        parsed = urlsplit(raw_path)
        path = parsed.path or ""
        query_params = self._parse_query_string(parsed.query)
        self.logger.debug("[Dispatch] Parsed path: %s, Query params: %s", path, query_params)
        
        base_payload = dict(payload) if payload else {}

        self.logger.debug("[Dispatch] Procurando handler para %s %s entre %d handlers", method, path, len(self._handlers))
        
        for handler in self._handlers:
            self.logger.debug("[Dispatch] Testando handler: %s %s", handler.method, handler.template)
            if handler.method != method:
                self.logger.debug("[Dispatch] Method não confere: %s != %s", handler.method, method)
                continue
            match = handler.match(path)
            if match is None:
                self.logger.debug("[Dispatch] Path não confere com template %s", handler.template)
                continue
            
            self.logger.info("[Dispatch] Handler encontrado: %s %s", handler.method, handler.template)
            self.logger.debug("[Dispatch] Path params extraídos: %s", match)

            payload_data = dict(base_payload)
            if not handler.expect_query:
                for key, value in query_params.items():
                    payload_data.setdefault(key, value)
            
            self.logger.debug("[Dispatch] Payload final: %s", _to_json(payload_data))

            args: list[str] = []
            for name in handler.param_names:
                value = self._resolve_path_value(name, match, payload_data, query_params, handler.template)
                args.append(value)
                self.logger.debug("[Dispatch] Path param %s = %s", name, value)

            self.logger.info("[Dispatch] Executando handler %s com args=%s", handler.func.__name__, args)
            self.logger.debug("[Dispatch] Handler expects - payload: %s, query: %s", handler.expect_payload, handler.expect_query)
            
            try:
                if handler.expect_payload and handler.expect_query:
                    result = handler.func(*args, payload_data, query_params)
                elif handler.expect_payload:
                    result = handler.func(*args, payload_data)
                elif handler.expect_query:
                    result = handler.func(*args, query_params)
                else:
                    result = handler.func(*args)
                
                self.logger.info("[Dispatch] Handler %s executado com SUCESSO", handler.func.__name__)
                self.logger.debug("[Dispatch] Resultado do handler: %s", _to_json(result))
                return result
                
            except Exception as exc:
                self.logger.exception("[Dispatch] ERRO executando handler %s: %s", handler.func.__name__, exc)
                raise

        self.logger.error("[Dispatch] Nenhum handler encontrado para: %s", endpoint)
        raise ValueError(f"Endpoint nao suportado: {endpoint}")

    def _parse_query_string(self, query: str) -> Dict[str, Any]:
        if not query:
            return {}
        collected: Dict[str, List[str]] = {}
        for key, value in parse_qsl(query, keep_blank_values=True):
            collected.setdefault(key, []).append(value)
        result: Dict[str, Any] = {}
        for key, values in collected.items():
            if len(values) == 1:
                result[key] = values[0]
            else:
                result[key] = values
        return result

    def _resolve_path_value(
        self,
        name: str,
        path_values: Dict[str, str],
        payload: Dict[str, Any],
        query_params: Dict[str, Any],
        template: str,
    ) -> str:
        if name in path_values and path_values[name]:
            return str(path_values[name])
        for alias in self._path_param_aliases(name):
            if alias in path_values and path_values[alias]:
                return str(path_values[alias])
            if alias in payload and payload[alias] not in (None, ""):
                value = payload[alias]
                if isinstance(value, (list, tuple)):
                    value = value[0]
                return str(value)
            if alias in query_params and query_params[alias] not in (None, ""):
                value = query_params[alias]
                if isinstance(value, list):
                    value = value[0]
                return str(value)
        raise ValueError(f"Identifier {name} missing for endpoint {template}")

    def _path_param_aliases(self, name: str) -> List[str]:
        alias_map: Dict[str, List[str]] = {
            "identifier": ["identifier", "id", "event", "event_id", "person", "person_id", "series_id", "recurrence_id"],
            "person_id": ["person_id", "identifier", "id", "person"],
            "series_id": ["series_id", "identifier", "id"],
            "recurrence_id": ["recurrence_id", "identifier", "id"],
        }
        return alias_map.get(name, [name])

    def _clean_string(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        return text or None

    def _coerce_str_list(self, value: Any) -> List[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else None
        if isinstance(value, (list, tuple, set)):
            items: List[str] = []
            for item in value:
                text_item = str(item).strip()
                if text_item:
                    items.append(text_item)
            return items or None
        text = str(value).strip()
        return [text] if text else None

    def _dump_config(self, config: Any) -> Dict[str, Any]:
        packs_payload: Dict[int, List[str]] = {}
        for key, members in config.packs.items():
            packs_payload[int(key)] = list(members)
        return {
            "general": {
                "timezone": config.general.timezone,
                "default_view_days": config.general.default_view_days,
                "name_width": config.general.name_width,
                "overlap_minutes": config.general.overlap_minutes,
                "default_locale": config.general.default_locale,
            },
            "fairness": {
                "fair_window_days": config.fairness.fair_window_days,
                "role_rot_window_days": config.fairness.role_rot_window_days,
                "workload_tolerance": config.fairness.workload_tolerance,
            },
            "weights": {
                "load_balance": config.weights.load_balance,
                "recency": config.weights.recency,
                "role_rotation": config.weights.role_rotation,
                "morning_pref": config.weights.morning_pref,
                "solene_bonus": config.weights.solene_bonus,
            },
            "packs": packs_payload,
        }

    def _create_event(self, payload: Dict[str, Any]) -> Any:
        community = str(payload["community"]).strip()
        if not community:
            raise ValueError("community is required")

        date_str = self._parse_date(payload["date"])
        time_str = self._parse_time(payload["time"])
        quantity = self._parse_int(payload["quantity"], field="quantity")
        kind = str(payload.get("kind", "REG")).upper().strip() or "REG"
        pool = self._parse_uuid_list(payload.get("pool"))
        dtend_value = self._parse_datetime(payload.get("dtend"))
        tz_name = self.container.config.general.timezone

        return self.container.mutate(
            self.container.service.create_event,
            community=community,
            date_str=date_str,
            time_str=time_str,
            tz_name=tz_name,
            quantity=quantity,
            kind=kind,
            pool=pool,
            dtend=dtend_value,
        )

    def _get_event_detail(self, identifier: str) -> Dict[str, Any]:
        def action() -> Dict[str, Any]:
            event = self.container.service.get_event(identifier)
            data = self._serialize_event(event)
            assignments = self.container.service.state.assignments.get(event.id, {})
            people = self.container.service.state.people
            data["assignments"] = [
                {
                    "role": role,
                    "person_id": str(pid),
                    "person_name": people.get(pid).name if people.get(pid) else None,
                }
                for role, pid in sorted(assignments.items())
            ]
            return data

        return self.container.read(action)

    def _update_event(self, identifier: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        updates = self._ensure_dict(payload)
        community_value: str | None = None
        if "community" in updates:
            community_value = str(updates["community"]).strip()
            if not community_value:
                raise ValueError("community cannot be empty.")
        date_value: str | None = None
        if "date" in updates:
            date_value = self._parse_date(updates["date"])
        time_value: str | None = None
        if "time" in updates:
            time_value = self._parse_time(updates["time"])
        quantity_value: int | None = None
        if "quantity" in updates:
            quantity_value = self._parse_int(updates["quantity"], field="quantity")
        kind_value: str | None = None
        if "kind" in updates:
            kind = str(updates["kind"]).strip()
            kind_value = kind.upper() if kind else None
        pool_value = self._parse_uuid_list(updates.get("pool")) if "pool" in updates else None
        dtend_value = self._parse_datetime(updates["dtend"]) if "dtend" in updates else None

        if all(
            value is None
            for value in (
                community_value,
                date_value,
                time_value,
                quantity_value,
                kind_value,
                pool_value,
                dtend_value,
            )
        ):
            raise ValueError("Nenhuma alteracao informada para o evento.")

        event = self.container.mutate(
            self.container.service.update_event,
            identifier,
            community=community_value,
            date_str=date_value,
            time_str=time_value,
            quantity=quantity_value,
            kind=kind_value,
            pool=pool_value,
            tz_name=self.container.config.general.timezone,
            dtend=dtend_value,
        )
        return self._serialize_event(event)

    def _delete_event(self, identifier: str) -> Dict[str, Any]:
        if not identifier:
            raise ValueError("Event identifier is required for deletion.")

        self.container.mutate(self.container.service.remove_event, str(identifier))
        return {"detail": f"Evento {identifier} removido."}

    def _list_events(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        filters = self._ensure_dict(payload)
        communities = filters.get("community") or filters.get("communities")
        if isinstance(communities, str):
            communities = [communities]
        community_filters = {str(c).strip() for c in (communities or []) if str(c).strip()}

        start_date = self._parse_optional_date(filters.get("start") or filters.get("after"))
        end_date = self._parse_optional_date(filters.get("end") or filters.get("before"))
        specific_date = self._parse_optional_date(filters.get("date"))
        kind_filter = str(filters.get("kind", "")).upper().strip()
        key_filter = str(filters.get("key", "")).strip()

        events = self.container.read(self.container.service.list_events)
        items: List[Dict[str, Any]] = []
        for event in events:
            if community_filters and event.community not in community_filters:
                continue
            event_date = event.dtstart.date()
            if specific_date and event_date != specific_date:
                continue
            if start_date and event_date < start_date:
                continue
            if end_date and event_date > end_date:
                continue
            if kind_filter and event.kind != kind_filter:
                continue
            if key_filter and event.key() != key_filter:
                continue
            items.append(self._serialize_event(event))
        return items

    def _get_event_pool(self, identifier: str) -> Dict[str, Any]:
        return self.container.read(lambda: self.container.service.pool_info(identifier))

    def _set_event_pool(self, identifier: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._ensure_dict(payload)
        members = data.get("members")
        if members is None:
            raise ValueError("members is required to set the pool.")
        pool_members = self._parse_uuid_list(members) or []
        self.container.mutate(self.container.service.set_pool, identifier, pool_members)
        return self.container.read(lambda: self.container.service.pool_info(identifier))

    def _clear_event_pool(self, identifier: str) -> Dict[str, Any]:
        self.container.mutate(self.container.service.clear_pool, identifier)
        return self.container.read(lambda: self.container.service.pool_info(identifier))

    def _list_series(self) -> List[Dict[str, Any]]:
        items = self.container.read(lambda: list(self.container.service.state.series.values()))
        return [self._to_serializable(item) for item in items]

    def _create_series(self, payload: Dict[str, Any]) -> Any:
        base_event_id = self._parse_uuid(payload["base_event_id"], field="base_event_id")
        days = self._parse_int(payload["days"], field="days")
        kind = str(payload.get("kind", "REG")).upper().strip() or "REG"
        pool = self._parse_uuid_list(payload.get("pool"))

        return self.container.mutate(
            self.container.service.create_series,
            base_event_id=base_event_id,
            days=days,
            kind=kind,
            pool=pool,
        )

    def _update_series(self, series_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        updates = self._ensure_dict(payload)
        if "new_base_event_id" not in updates and "pool" not in updates:
            raise ValueError("Nenhuma alteracao informada para a serie.")

        series_uuid = self._parse_uuid(series_id, field="series_id")
        base_uuid = None
        if "new_base_event_id" in updates and updates["new_base_event_id"] not in (None, ""):
            base_uuid = self._parse_uuid(updates["new_base_event_id"], field="new_base_event_id")
        pool_value = self._parse_uuid_list(updates.get("pool")) if "pool" in updates else None

        def action() -> Any:
            current = self.container.service.state.series.get(series_uuid)
            if not current:
                raise ValidationError("Serie nao encontrada.")
            target_base = base_uuid or current.base_event_id
            return self.container.service.rebase_series(
                series_id=series_uuid,
                new_base_event_id=target_base,
                pool=pool_value,
            )

        series = self.container.mutate(action)
        return self._to_serializable(series)

    def _delete_series(self, series_id: str) -> Dict[str, Any]:
        series_uuid = self._parse_uuid(series_id, field="series_id")
        self.container.mutate(self.container.service.remove_series, series_uuid)
        return {"detail": f"Serie {series_id} removida."}

    def _list_recurrences(self) -> List[Dict[str, Any]]:
        items = self.container.read(lambda: list(self.container.service.state.recurrences.values()))
        return [self._to_serializable(item) for item in items]

    def _create_recurrence(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._ensure_dict(payload)
        community = str(data["community"]).strip()
        if not community:
            raise ValueError("community is required.")
        dtstart = self._parse_datetime(data.get("dtstart_base"))
        if dtstart is None:
            raise ValueError("dtstart_base must be an ISO datetime string.")
        rrule = str(data.get("rrule", "")).strip()
        if not rrule:
            raise ValueError("rrule is required.")
        quantity = self._parse_int(data["quantity"], field="quantity")
        pool = self._parse_uuid_list(data.get("pool"))
        item = self.container.mutate(
            self.container.service.create_recurrence,
            community=community,
            dtstart_base=dtstart,
            rrule=rrule,
            quantity=quantity,
            pool=pool,
        )
        return self._to_serializable(item)

    def _update_recurrence(self, recurrence_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        updates = self._ensure_dict(payload)
        if not updates:
            raise ValueError("Nenhuma alteracao informada para a recorrencia.")
        recurrence_uuid = self._parse_uuid(recurrence_id, field="recurrence_id")
        rrule = None
        if "rrule" in updates:
            value = str(updates["rrule"]).strip()
            rrule = value or None
        quantity = None
        if "quantity" in updates:
            quantity = self._parse_int(updates["quantity"], field="quantity")
        pool = self._parse_uuid_list(updates.get("pool")) if "pool" in updates else None
        item = self.container.mutate(
            self.container.service.update_recurrence,
            recurrence_uuid,
            rrule=rrule,
            quantity=quantity,
            pool=pool,
        )
        return self._to_serializable(item)

    def _delete_recurrence(self, recurrence_id: str) -> Dict[str, Any]:
        recurrence_uuid = self._parse_uuid(recurrence_id, field="recurrence_id")
        self.container.mutate(self.container.service.remove_recurrence, recurrence_uuid)
        return {"detail": f"Recorrencia {recurrence_id} removida."}

    def _create_person(self, payload: Dict[str, Any]) -> Any:
        name = str(payload["name"]).strip()
        if not name:
            raise ValueError("name is required")
        community = str(payload["community"]).strip()
        if not community:
            raise ValueError("community is required")

        roles = payload.get("roles") or []
        if not isinstance(roles, list):
            raise ValueError("roles must be a list when provided.")
        morning = bool(payload.get("morning", False))
        active = bool(payload.get("active", True))
        locale = payload.get("locale")
        if locale is not None:
            locale = str(locale).strip() or None

        return self.container.mutate(
            self.container.service.add_person,
            name=name,
            community=community,
            roles=roles,
            morning=morning,
            active=active,
            locale=locale,
        )

    def _list_people(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        filters = self._ensure_dict(payload)
        name_filter = filters.get("name") or filters.get("search")
        community_filter = filters.get("community")
        active_filter = filters.get("active")
        morning_filter = filters.get("morning")

        name_tokens: List[str] = []
        if name_filter:
            normalized_name = self._normalize_text(name_filter)
            name_tokens = [token for token in normalized_name.split() if token]

        community_token: str | None = None
        if community_filter:
            community_token = str(community_filter).strip().upper()

        active_value: bool | None = None
        if active_filter is not None:
            active_value = self._parse_bool(active_filter, field="active")

        morning_value: bool | None = None
        if morning_filter is not None:
            morning_value = self._parse_bool(morning_filter, field="morning")

        people = self.container.read(self.container.service.list_people)
        results: List[Dict[str, Any]] = []
        for person in people:
            person_dict = person.to_dict()
            if name_tokens:
                person_name = self._normalize_text(person.name)
                if not all(token in person_name for token in name_tokens):
                    continue
            if community_token and person.community != community_token:
                continue
            if active_value is not None and person.active != active_value:
                continue
            if morning_value is not None and person.morning != morning_value:
                continue
            results.append(person_dict)
        return results

    def _get_person(self, identifier: str) -> Dict[str, Any]:
        person_id = self._parse_uuid(identifier, field="person_id")
        data = self.container.read(lambda: self.container.service.person_detail(person_id))
        data["id"] = str(person_id)
        return self._to_serializable(data)

    def _update_person(self, identifier: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        person_id = self._parse_uuid(identifier, field="person_id")
        updates = self._ensure_dict(payload)

        allowed_fields = {"name", "community", "roles", "morning", "active", "locale"}
        sanitized: Dict[str, Any] = {}
        for key in allowed_fields:
            if key not in updates:
                continue
            value = updates[key]
            if key == "name" and value is not None:
                name_value = str(value).strip()
                if not name_value:
                    raise ValueError("name cannot be empty.")
                sanitized[key] = name_value
                continue
            if key == "community" and value is not None:
                community_value = str(value).strip()
                if not community_value:
                    raise ValueError("community cannot be empty.")
                sanitized[key] = community_value
                continue
            if key == "roles":
                if value is None:
                    sanitized[key] = []
                elif isinstance(value, list):
                    sanitized[key] = [str(item).strip() for item in value if str(item).strip()]
                else:
                    raise ValueError("roles must be a list when provided.")
                continue
            if key == "morning" and value is not None:
                sanitized[key] = self._parse_bool(value, field="morning")
                continue
            if key == "active" and value is not None:
                sanitized[key] = self._parse_bool(value, field="active")
                continue
            if key == "locale":
                sanitized[key] = str(value).strip() if value is not None else None
                continue

        if not sanitized:
            raise ValueError("No fields provided to update the person.")

        person = self.container.mutate(
            self.container.service.update_person,
            person_id,
            **sanitized,
        )
        return person.to_dict()

    def _delete_person(self, identifier: str) -> Dict[str, Any]:
        person_id = self._parse_uuid(identifier, field="person_id")
        self.container.mutate(self.container.service.remove_person, person_id)
        return {"detail": f"Pessoa {identifier} removida."}

    def _list_person_blocks(self, person_id: str) -> List[Dict[str, Any]]:
        pid = self._parse_uuid(person_id, field="person_id")
        blocks = self.container.read(lambda: self.container.service.list_blocks(pid))
        return [block.to_dict() for block in blocks]

    def _add_person_block(self, person_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        pid = self._parse_uuid(person_id, field="person_id")
        data = self._ensure_dict(payload)
        start_dt = self._parse_datetime(data.get("start"))
        if start_dt is None:
            raise ValueError("start datetime is required.")
        end_dt = self._parse_datetime(data.get("end"))
        if end_dt is None:
            raise ValueError("end datetime is required.")
        note = data.get("note")
        if note is not None:
            note = str(note).strip() or None
        self.container.mutate(
            self.container.service.add_block,
            pid,
            start=start_dt,
            end=end_dt,
            note=note,
        )
        return {"detail": "Bloqueio adicionado."}

    def _remove_person_block(
        self,
        person_id: str,
        payload: Dict[str, Any],
        query_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        pid = self._parse_uuid(person_id, field="person_id")
        merged = self._ensure_dict(payload)
        for key, value in query_params.items():
            merged.setdefault(key, value)
        remove_all = False
        if "all" in merged:
            remove_all = self._parse_bool(merged["all"], field="all")
        elif "remove_all" in merged:
            remove_all = self._parse_bool(merged["remove_all"], field="remove_all")
        index_value = merged.get("index")
        index_int = None
        if index_value is not None:
            index_int = self._parse_int(index_value, field="index")
        if not remove_all and index_int is None:
            raise ValueError("Informe all=true ou um index para remover o bloqueio.")
        self.container.mutate(
            self.container.service.remove_block,
            pid,
            index=index_int,
            remove_all=remove_all,
        )
        return {"detail": "Bloqueio removido."}

    def _schedule_list(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        filters = self._ensure_dict(payload)
        periodo = self._clean_string(filters.get("periodo"))
        de = self._clean_string(filters.get("de"))
        ate = self._clean_string(filters.get("ate"))
        communities = self._coerce_str_list(filters.get("communities") or filters.get("community"))
        roles = self._coerce_str_list(filters.get("roles"))
        return self.container.read(
            lambda: self.container.service.list_schedule(
                periodo=periodo,
                de=de,
                ate=ate,
                communities=communities,
                roles=roles,
            )
        )

    def _schedule_free(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        filters = self._ensure_dict(payload)
        periodo = self._clean_string(filters.get("periodo"))
        de = self._clean_string(filters.get("de"))
        ate = self._clean_string(filters.get("ate"))
        communities = self._coerce_str_list(filters.get("communities") or filters.get("community"))
        return self.container.read(
            lambda: self.container.service.list_free_slots(
                periodo=periodo,
                de=de,
                ate=ate,
                communities=communities,
            )
        )

    def _schedule_check(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        filters = self._ensure_dict(payload)
        periodo = self._clean_string(filters.get("periodo"))
        de = self._clean_string(filters.get("de"))
        ate = self._clean_string(filters.get("ate"))
        communities = self._coerce_str_list(filters.get("communities") or filters.get("community"))
        return self.container.read(
            lambda: self.container.service.check_schedule(
                periodo=periodo,
                de=de,
                ate=ate,
                communities=communities,
            )
        )

    def _schedule_stats(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        filters = self._ensure_dict(payload)
        periodo = self._clean_string(filters.get("periodo"))
        de = self._clean_string(filters.get("de"))
        ate = self._clean_string(filters.get("ate"))
        communities = self._coerce_str_list(filters.get("communities") or filters.get("community"))
        return self.container.read(
            lambda: self.container.service.stats(
                periodo=periodo,
                de=de,
                ate=ate,
                communities=communities,
            )
        )

    def _schedule_suggestions(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        filters = self._ensure_dict(payload)
        event_identifier = self._clean_string(filters.get("event"))
        if not event_identifier:
            raise ValueError("event parameter is required.")
        role = self._clean_string(filters.get("role"))
        if not role:
            raise ValueError("role parameter is required.")
        top_value = filters.get("top")
        top = self._parse_int(top_value, field="top") if top_value not in (None, "") else 5
        seed_value = filters.get("seed")
        seed = self._parse_int(seed_value, field="seed") if seed_value not in (None, "") else None
        return self.container.read(
            lambda: self.container.service.suggest_candidates(
                event_identifier,
                role,
                top=top,
                seed=seed,
            )
        )

    def _schedule_recalculate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        filters = self._ensure_dict(payload)
        periodo = self._clean_string(filters.get("periodo"))
        de = self._clean_string(filters.get("de"))
        ate = self._clean_string(filters.get("ate"))
        seed_value = filters.get("seed")
        seed = self._parse_int(seed_value, field="seed") if seed_value not in (None, "") else None
        self.container.mutate(
            self.container.service.recalculate,
            periodo=periodo,
            de=de,
            ate=ate,
            seed=seed,
        )
        return {"detail": "Escala recalculada."}

    def _schedule_reset(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        filters = self._ensure_dict(payload)
        periodo = self._clean_string(filters.get("periodo"))
        de = self._clean_string(filters.get("de"))
        ate = self._clean_string(filters.get("ate"))
        self.container.mutate(
            self.container.service.reset_assignments,
            periodo=periodo,
            de=de,
            ate=ate,
        )
        return {"detail": "Atribuicoes reiniciadas."}

    def _schedule_apply_assignment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._ensure_dict(payload)
        event_identifier = self._clean_string(data.get("event"))
        role = self._clean_string(data.get("role"))
        if not event_identifier or not role:
            raise ValueError("event and role are required.")
        person_id = self._parse_uuid(data["person_id"], field="person_id")
        self.container.mutate(
            self.container.service.apply_assignment,
            event_identifier,
            role,
            person_id,
        )
        return {"detail": "Atribuicao aplicada."}

    def _schedule_clear_assignment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._ensure_dict(payload)
        event_identifier = self._clean_string(data.get("event"))
        role = self._clean_string(data.get("role"))
        if not event_identifier or not role:
            raise ValueError("event and role are required.")
        self.container.mutate(
            self.container.service.clear_assignment,
            event_identifier,
            role,
        )
        return {"detail": "Atribuicao removida."}

    def _schedule_swap_assignments(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._ensure_dict(payload)
        event_a = self._clean_string(data.get("event_a"))
        role_a = self._clean_string(data.get("role_a"))
        event_b = self._clean_string(data.get("event_b"))
        role_b = self._clean_string(data.get("role_b"))
        if not all([event_a, role_a, event_b, role_b]):
            raise ValueError("event_a, role_a, event_b e role_b sao obrigatorios.")
        self.container.mutate(
            self.container.service.swap_assignments,
            event_a,
            role_a,
            event_b,
            role_b,
        )
        return {"detail": "Atribuicoes trocadas."}

    def _get_config(self) -> Dict[str, Any]:
        return self._dump_config(self.container.config)

    def _update_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._ensure_dict(payload)
        required = {"general", "fairness", "weights", "packs"}
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"Campos obrigatorios ausentes na configuracao: {', '.join(sorted(missing))}.")
        general_cfg = GeneralConfig(**self._ensure_dict(data["general"]))
        fairness_cfg = FairnessConfig(**self._ensure_dict(data["fairness"]))
        weights_cfg = WeightConfig(**self._ensure_dict(data["weights"]))
        packs_raw = data["packs"]
        if not isinstance(packs_raw, dict):
            raise ValueError("packs deve ser um objeto com chaves numericas.")
        packs: Dict[int, List[str]] = {}
        for key, members in packs_raw.items():
            key_int = int(key)
            members_list = self._coerce_str_list(members) or []
            packs[key_int] = [item.upper() for item in members_list]
        config_cls = self.container.config.__class__
        cfg = config_cls(
            general=general_cfg,
            fairness=fairness_cfg,
            weights=weights_cfg,
            packs={key: list(values) for key, values in packs.items()},
        )
        cfg.validate()
        self.container.set_config(cfg, persist=True)
        return self._dump_config(cfg)

    def _reload_config(self) -> Dict[str, Any]:
        cfg = self.container.reload_config()
        return self._dump_config(cfg)

    def _save_state(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._ensure_dict(payload)
        path_value = self._clean_string(data.get("path"))
        target = self.container.save_state(path_value)
        return {"path": str(target)}

    def _load_state(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self._ensure_dict(payload)
        path_value = self._clean_string(data.get("path"))
        if not path_value:
            raise ValueError("path is required to load state.")
        target = self.container.load_state(path_value)
        return {"path": str(target)}

    def _undo_last(self) -> Dict[str, Any]:
        label = self.container.undo()
        if not label:
            raise ValueError("Nada para desfazer.")
        message = self.container.localizer.text("undo.applied", label=label)
        return {"message": message}

    def _resolve_endpoint(self, endpoint: Any, stored: Dict[str, Any]) -> str:
        if endpoint is None:
            raise ValueError('Endpoint is required for every api_call.')
        if not isinstance(endpoint, str):
            raise ValueError('Endpoint must be a string.')
        if '{{' not in endpoint:
            return endpoint

        def replacer(match: re.Match[str]) -> str:
            reference = match.group(1).strip()
            value = self._lookup_reference(reference, stored)
            return '' if value is None else str(value)

        resolved = PLACEHOLDER_PATTERN.sub(replacer, endpoint)
        if '{{' in resolved:
            raise ValueError(f'Unresolved placeholder in endpoint {endpoint}')
        return resolved

    def _resolve_placeholders(self, value: Any, stored: Dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {key: self._resolve_placeholders(val, stored) for key, val in value.items()}
        if isinstance(value, list):
            return [self._resolve_placeholders(item, stored) for item in value]
        if isinstance(value, str):
            matches = PLACEHOLDER_PATTERN.findall(value)
            if not matches:
                return value
            if PLACEHOLDER_PATTERN.fullmatch(value):
                reference = matches[0].strip()
                return self._lookup_reference(reference, stored)

            def replacer(match: re.Match[str]) -> str:
                reference = match.group(1).strip()
                replacement = self._lookup_reference(reference, stored)
                return "" if replacement is None else str(replacement)

            return PLACEHOLDER_PATTERN.sub(replacer, value)
        return value

    def _lookup_reference(self, reference: str, stored: Dict[str, Any]) -> Any:
        tokens = self._split_reference(reference)
        if not tokens:
            raise ValueError(f"Invalid placeholder reference: {reference}")

        root = tokens.pop(0)
        if root not in stored:
            raise ValueError(f"Unknown reference '{root}' in placeholder {reference}")

        value: Any = stored[root]
        for token in tokens:
            token = token.strip()
            if isinstance(value, list):
                if not token.isdigit():
                    raise ValueError(f"List index expected in reference {reference}")
                index = int(token)
                value = value[index]
            elif isinstance(value, dict):
                if token not in value:
                    raise ValueError(f"Key '{token}' missing in reference {reference}")
                value = value[token]
            else:
                raise ValueError(f"Cannot access '{token}' inside reference {reference}")
        return value

    def _split_reference(self, reference: str) -> List[str]:
        tokens: List[str] = []
        buffer = ""
        i = 0
        length = len(reference)
        while i < length:
            char = reference[i]
            if char == ".":
                if buffer:
                    tokens.append(buffer.strip())
                    buffer = ""
                i += 1
                continue
            if char == "[":
                if buffer:
                    tokens.append(buffer.strip())
                    buffer = ""
                end = reference.find("]", i)
                if end == -1:
                    raise ValueError(f"Unclosed bracket in reference {reference}")
                tokens.append(reference[i + 1 : end].strip())
                i = end + 1
                continue
            buffer += char
            i += 1
        if buffer:
            tokens.append(buffer.strip())
        return [token for token in tokens if token]

    def _serialize_event(self, event: Any) -> Dict[str, Any]:
        data = self._to_serializable(event)
        if not isinstance(data, dict):
            raise ValueError("Unexpected event serialization output")
        key_getter = getattr(event, "key", None)
        if callable(key_getter):
            data.setdefault("key", key_getter())
        return data

    def _to_serializable(self, obj: Any) -> Any:
        if obj is None:
            return None
        if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
            data = obj.to_dict()  # type: ignore[call-arg]
            key_getter = getattr(obj, "key", None)
            if callable(key_getter):
                try:
                    data.setdefault("key", key_getter())
                except Exception:  # pragma: no cover - best effort only
                    pass
            return self._to_serializable(data)
        if isinstance(obj, dict):
            return {str(key): self._to_serializable(value) for key, value in obj.items()}
        if isinstance(obj, list):
            return [self._to_serializable(item) for item in obj]
        if isinstance(obj, set):
            return [self._to_serializable(item) for item in sorted(obj, key=str)]
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, time):
            return obj.isoformat(timespec="minutes")
        return obj

    def _ensure_dict(self, payload: Any) -> Dict[str, Any]:
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object.")
        return payload

    def _normalize_text(self, value: Any) -> str:
        return strip_diacritics(str(value or "").strip()).lower()

    def _parse_bool(self, value: Any, *, field: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = self._normalize_text(value)
            if normalized in {"true", "1", "yes", "on", "sim"}:
                return True
            if normalized in {"false", "0", "no", "off", "nao"}:
                return False
        if isinstance(value, (int, float)):
            if value in {0, 1}:
                return bool(value)
        raise ValueError(f"{field} must be a boolean value.")

    def _parse_date(self, value: Any) -> str:
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, str):
            return date.fromisoformat(value).isoformat()
        raise ValueError("date must be provided as ISO string.")

    def _parse_optional_date(self, value: Any) -> date | None:
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
        raise ValueError("Expected ISO date string.")

    def _parse_time(self, value: Any) -> str:
        if isinstance(value, time):
            return value.strftime("%H:%M")
        if isinstance(value, str):
            parsed = time.fromisoformat(value)
            return parsed.strftime("%H:%M")
        raise ValueError("time must be provided as ISO string.")

    def _parse_datetime(self, value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise ValueError("dtend must be an ISO datetime string when provided.")

    def _parse_int(self, value: Any, *, field: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be an integer.") from exc

    def _parse_uuid(self, value: Any, *, field: str) -> UUID:
        if isinstance(value, UUID):
            return value
        if isinstance(value, str):
            return UUID(value)
        raise ValueError(f"{field} must be a UUID string.")

    def _parse_uuid_list(self, value: Any) -> Sequence[UUID] | None:
        if value in (None, ""):
            return None
        if isinstance(value, (list, tuple, set)):
            return [self._parse_uuid(item, field="pool item") for item in value]
        raise ValueError("pool must be a list of UUID strings when provided.")







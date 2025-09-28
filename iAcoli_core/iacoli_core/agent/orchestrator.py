from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from urllib.parse import parse_qsl, urlsplit
from typing import Any, Callable, Dict, List, Sequence
from uuid import UUID

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - package may be optional locally
    OpenAI = None  # type: ignore[assignment]

from ..config import FairnessConfig, GeneralConfig, WeightConfig
from ..errors import ValidationError
from ..utils import strip_diacritics
from ..webapp.container import ServiceContainer
from .prompt_builder import build_system_prompt

PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
PATH_PARAM_PATTERN = re.compile(r"{([^{}]+)}")


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
        system_prompt = build_system_prompt(user_prompt)
        raw_output = self._call_llm(system_prompt, user_prompt)
        if raw_output is None:
            return {
                "response_text": "Desculpe, nao consegui processar seu pedido agora.",
                "executed_actions": [],
            }

        parsed = self._parse_llm_output(raw_output)
        if parsed is None:
            return {
                "response_text": "Desculpe, recebi um retorno invalido do agente.",
                "executed_actions": [],
            }

        api_calls = parsed.get("api_calls")
        if not isinstance(api_calls, list):
            api_calls = []

        executed_actions = self._execute_calls(api_calls)
        response_text = parsed.get("response_text") or "Tudo certo, acao concluida."

        if executed_actions and executed_actions[-1].get("status") not in {"success", "noop"}:
            response_text = "Desculpe, ocorreu um erro ao executar as acoes planejadas."

        return {
            "response_text": response_text,
            "executed_actions": executed_actions,
        }

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str | None:
        if OpenAI is None:
            self.logger.error("openai package not installed. Cannot reach Perplexity Sonar.")
            return None

        api_key = os.environ.get("PPLX_API_KEY")
        if not api_key:
            self.logger.error("Missing PPLX_API_KEY environment variable.")
            return None

        client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = client.chat.completions.create(
                model="sonar",
                messages=messages,
                # PARÂMETRO CRÍTICO PARA DESATIVAR PESQUISA WEB:
                extra_body={"disable_search": True}
            )
        except Exception as exc:  # pragma: no cover - network call
            self.logger.exception("Failed to call Perplexity Sonar: %s", exc)
            return None

        if not response.choices:
            self.logger.error("LLM response has no choices.")
            return None

        message = response.choices[0].message
        if message is None:
            self.logger.error("LLM response message is empty.")
            return None

        return message.content or None

    def _parse_llm_output(self, raw_output: str) -> Dict[str, Any] | None:
        if not raw_output:
            self.logger.error("LLM output is empty")
            return None
            
        # Limpa a saída removendo possíveis formatações markdown
        cleaned_output = raw_output.strip()
        
        # Remove blocos de código markdown se existirem
        if cleaned_output.startswith("```json"):
            cleaned_output = cleaned_output[7:]
        if cleaned_output.startswith("```"):
            cleaned_output = cleaned_output[3:]
        if cleaned_output.endswith("```"):
            cleaned_output = cleaned_output[:-3]
            
        # Corrige chaves duplas nas extremidades que o modelo pode ter usado por conta do exemplo no prompt
        if cleaned_output.startswith("{{"):
            cleaned_output = cleaned_output[1:]
        if cleaned_output.endswith("}}"):
            cleaned_output = cleaned_output[:-1]

        cleaned_output = cleaned_output.strip()
        
        # Log da saída para debug
        self.logger.info(f"Raw LLM output: {repr(raw_output[:200])}...")
        self.logger.info(f"Cleaned LLM output: {repr(cleaned_output[:200])}...")
        
        decoder = json.JSONDecoder()
        try:
            data = json.loads(cleaned_output)
        except json.JSONDecodeError as exc:
            self.logger.error("LLM output is not valid JSON after cleaning: %s", exc)
            self.logger.error("Problematic output: %r", cleaned_output[:500])
            try:
                data, end = decoder.raw_decode(cleaned_output)
                trailing = cleaned_output[end:].strip()
                if trailing:
                    self.logger.info("Ignorando texto extra apos JSON: %r", trailing[:80])
            except json.JSONDecodeError:
                corrected_output = self._try_fix_json(cleaned_output)
                if not corrected_output:
                    return None
                try:
                    data = json.loads(corrected_output)
                    if corrected_output != cleaned_output:
                        self.logger.info("JSON corrigido automaticamente")
                except json.JSONDecodeError as inner_exc:
                    self.logger.error("Nao foi possivel corrigir o JSON automaticamente: %s", inner_exc)
                    return None

        if not isinstance(data, dict):
            self.logger.error("LLM output is not a JSON object: %r", data)
            return None

        return data

    def _try_fix_json(self, json_str: str) -> str | None:
        """Tenta extrair ou completar o primeiro objeto JSON bem formado devolvido pelo modelo."""
        text = (json_str or "").strip()
        if not text:
            return None

        start = text.find("{")
        if start == -1:
            return None

        candidate = text[start:]
        stack: list[str] = []
        in_string = False
        escape = False
        end_index: int | None = None

        for index, char in enumerate(candidate):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char == '{':
                stack.append('}')
                continue

            if char == '[':
                stack.append(']')
                continue

            if char in (']', '}'):
                if not stack:
                    end_index = index
                    break
                while stack:
                    expected = stack[-1]
                    if expected == char:
                        stack.pop()
                        break
                    stack.pop()
                else:
                    end_index = index
                    break
                if not stack:
                    end_index = index + 1
                    break
                continue

            if not stack and index != 0:
                end_index = index
                break

        if end_index is None:
            if not stack:
                end_index = len(candidate)
            else:
                missing_closers = ''.join(reversed(stack))
                self.logger.info("Complementando JSON com fechamentos: %s", missing_closers)
                return (candidate + missing_closers).strip()

        result = candidate[:end_index].strip()
        trailing = candidate[end_index:].strip()
        if trailing:
            self.logger.info("Ignorando texto extra apos JSON: %r", trailing[:80])

        if stack:
            missing_closers = ''.join(reversed(stack))
            self.logger.info("Complementando JSON com fechamentos: %s", missing_closers)
            result += missing_closers

        return result or None

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
        if not isinstance(endpoint, str):
            raise ValueError("Endpoint deve ser uma string no formato 'METHOD /path'.")

        parts = endpoint.strip().split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Formato de endpoint invalido: {endpoint}")

        method, raw_path = parts[0].upper(), parts[1]
        parsed = urlsplit(raw_path)
        path = parsed.path or ""
        query_params = self._parse_query_string(parsed.query)
        base_payload = dict(payload) if payload else {}

        for handler in self._handlers:
            if handler.method != method:
                continue
            match = handler.match(path)
            if match is None:
                continue

            payload_data = dict(base_payload)
            if not handler.expect_query:
                for key, value in query_params.items():
                    payload_data.setdefault(key, value)

            args: list[str] = []
            for name in handler.param_names:
                value = self._resolve_path_value(name, match, payload_data, query_params, handler.template)
                args.append(value)

            if handler.expect_payload and handler.expect_query:
                return handler.func(*args, payload_data, query_params)
            if handler.expect_payload:
                return handler.func(*args, payload_data)
            if handler.expect_query:
                return handler.func(*args, query_params)
            return handler.func(*args)

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


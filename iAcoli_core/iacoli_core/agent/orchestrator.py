from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, time
from typing import Any, Dict, List, Sequence
from uuid import UUID

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - package may be optional locally
    OpenAI = None  # type: ignore[assignment]

from ..errors import ValidationError
from ..utils import strip_diacritics
from ..webapp.container import ServiceContainer
from .prompt_builder import build_system_prompt

PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")


class AgentOrchestrator:
    """Coordinates LLM guidance with direct calls into the core service."""

    def __init__(self, container: ServiceContainer) -> None:
        self.container = container
        self.logger = logging.getLogger(__name__)
        # Mapeamento de endpoints para métodos
        self.endpoint_map = {
            ("POST", "/api/events"): self._create_event,
            ("DELETE", "/api/events/{identifier}"): self._delete_event,
            ("GET", "/api/events"): self._list_events,
            ("POST", "/api/series"): self._create_series,
            ("POST", "/api/people"): self._create_person,
            ("GET", "/api/people"): self._list_people,
            ("GET", "/api/people/{identifier}"): self._get_person,
            ("PUT", "/api/people/{identifier}"): self._update_person,
            ("PATCH", "/api/people/{identifier}"): self._update_person,
        }

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
            raise ValueError("Endpoint é obrigatório para cada api_call.")

        parts = endpoint.strip().split()
        if len(parts) != 2:
            raise ValueError(f"Formato de endpoint inválido: {endpoint}")

        method, path = parts[0].upper(), parts[1]

        # Lógica para endpoints com placeholders (identificadores)
        if "{identifier}" in path:
            key_template = (method, path)
            if key_template in self.endpoint_map:
                # Extrai o identificador do payload ou da URL
                identifier = payload.get("identifier") or payload.get("person_id")
                if not identifier:
                    # Tenta extrair da URL se o LLM colocou lá diretamente
                    if "/api/events/" in path:
                        identifier = path.split("/api/events/")[1]
                    elif "/api/people/" in path:
                        identifier = path.split("/api/people/")[1]

                if not identifier:
                    raise ValueError(f"Identifier não encontrado no payload para o endpoint {endpoint}")
                
                # Para métodos de atualização, o identifier vai como primeiro argumento
                if method in {"PUT", "PATCH"}:
                    return self.endpoint_map[key_template](identifier, payload)
                else:
                    return self.endpoint_map[key_template](identifier)
        
        # Endpoints simples (sem placeholders)
        key = (method, path)
        if key in self.endpoint_map:
            return self.endpoint_map[key](payload)

        # Se chegou aqui, o endpoint não é suportado
        raise ValueError(f"Endpoint não suportado: {endpoint}")

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


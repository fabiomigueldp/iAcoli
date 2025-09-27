from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Mapping

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from .errors import ValidationError
from .models import DEFAULT_PACKS, ROLE_CODES, normalize_role

CONFIG_ENV_PREFIX = "ESCALA_"
DEFAULT_CONFIG_PATH = Path("config.toml")


@dataclass(slots=True)
class GeneralConfig:
    timezone: str = "America/Sao_Paulo"
    default_view_days: int = 30
    name_width: int = 18
    overlap_minutes: int = 110
    default_locale: str = "pt-BR"


@dataclass(slots=True)
class FairnessConfig:
    fair_window_days: int = 90
    role_rot_window_days: int = 45
    workload_tolerance: int = 2


@dataclass(slots=True)
class WeightConfig:
    load_balance: float = 80.0
    recency: float = 1.2
    role_rotation: float = -6.0
    morning_pref: float = 1.0
    solene_bonus: float = 0.8


@dataclass(slots=True)
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    fairness: FairnessConfig = field(default_factory=FairnessConfig)
    weights: WeightConfig = field(default_factory=WeightConfig)
    packs: Dict[int, list[str]] = field(default_factory=lambda: deepcopy(DEFAULT_PACKS))

    @classmethod
    def load(
        cls,
        path: Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
        overrides: Mapping[str, Any] | None = None,
    ) -> "Config":
        cfg = cls()
        cfg_path = path or DEFAULT_CONFIG_PATH
        if cfg_path.exists():
            data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
            cfg = cfg.merge_dict(data)
        if env:
            cfg = cfg.apply_env(env)
        if overrides:
            cfg = cfg.apply_overrides(overrides)
        cfg.validate()
        return cfg

    def merge_dict(self, data: Mapping[str, Any]) -> "Config":
        cfg = deepcopy(self)
        if "general" in data:
            cfg._assign_dataclass(cfg.general, data["general"])
        if "fairness" in data:
            cfg._assign_dataclass(cfg.fairness, data["fairness"])
        if "weights" in data:
            cfg._assign_dataclass(cfg.weights, data["weights"])
        if "packs" in data:
            packs: Dict[int, list[str]] = {}
            for key, value in data["packs"].items():
                packs[int(key)] = [normalize_role(role) for role in value]
            cfg.packs = packs
        return cfg

    def apply_env(self, env: Mapping[str, str]) -> "Config":
        payload: Dict[str, Dict[str, str]] = {}
        for key, value in env.items():
            if not key.startswith(CONFIG_ENV_PREFIX):
                continue
            remainder = key[len(CONFIG_ENV_PREFIX) :]
            pieces = [part for part in remainder.split("__") if part]
            if len(pieces) != 2:
                continue
            section, field_name = pieces
            payload.setdefault(section.lower(), {})[field_name.lower()] = value
        return self.merge_dict(payload)

    def apply_overrides(self, overrides: Mapping[str, Any]) -> "Config":
        cfg = deepcopy(self)
        for key, value in overrides.items():
            if key.startswith("general."):
                cfg._set_with_prefix(cfg.general, key, value)
            elif key.startswith("fairness."):
                cfg._set_with_prefix(cfg.fairness, key, value)
            elif key.startswith("weights."):
                cfg._set_with_prefix(cfg.weights, key, value)
            elif key.startswith("packs."):
                _, suffix = key.split(".", 1)
                index = int(suffix)
                roles = value
                if isinstance(roles, str):
                    roles = [token.strip() for token in roles.split(',') if token.strip()]
                cfg.packs[index] = [normalize_role(token) for token in roles]
            else:
                raise ValidationError(f"Override desconhecido: {key}")
        return cfg

    def _assign_dataclass(self, instance: Any, data: Mapping[str, Any]) -> None:
        for field_obj in fields(instance):
            name = field_obj.name
            if name not in data:
                continue
            value = self._convert_value(field_obj.type, data[name])
            setattr(instance, name, value)

    def _set_with_prefix(self, instance: Any, dotted_key: str, value: Any) -> None:
        _, field_name = dotted_key.split(".", 1)
        if not hasattr(instance, field_name):
            raise ValidationError(f"Campo desconhecido: {dotted_key}")
        field_obj = next(f for f in fields(instance) if f.name == field_name)
        setattr(instance, field_name, self._convert_value(field_obj.type, value))

    @staticmethod
    def _convert_value(expected_type: Any, value: Any) -> Any:
        if expected_type is bool:
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "sim"}
            return bool(value)
        if expected_type is int:
            return int(value)
        if expected_type is float:
            return float(value)
        if expected_type is str:
            return str(value)
        return value

    def validate(self) -> None:
        if self.general.default_view_days <= 0:
            raise ValidationError("default_view_days deve ser positivo")
        if self.general.name_width < 8:
            raise ValidationError("name_width minimo e 8")
        if self.general.overlap_minutes < 0:
            raise ValidationError("overlap_minutes nao pode ser negativo")
        if self.fairness.fair_window_days < 1:
            raise ValidationError("fair_window_days deve ser >= 1")
        if self.fairness.role_rot_window_days < 0:
            raise ValidationError("role_rot_window_days nao pode ser negativo")
        if self.fairness.workload_tolerance < 0:
            raise ValidationError("workload_tolerance nao pode ser negativo")
        for key, roles in self.packs.items():
            if key <= 0:
                raise ValidationError("Chaves de packs devem ser positivas")
            for role in roles:
                if role not in ROLE_CODES:
                    raise ValidationError(f"Funcao desconhecida no pack {key}: {role}")

    def to_toml(self) -> str:
        data = asdict(self)
        lines: list[str] = []
        lines.append("[general]")
        lines.append(f"timezone = \"{self.general.timezone}\"")
        lines.append(f"default_view_days = {self.general.default_view_days}")
        lines.append(f"name_width = {self.general.name_width}")
        lines.append(f"overlap_minutes = {self.general.overlap_minutes}")
        lines.append(f"default_locale = \"{self.general.default_locale}\"")
        lines.append("")
        lines.append("[fairness]")
        lines.append(f"fair_window_days = {self.fairness.fair_window_days}")
        lines.append(f"role_rot_window_days = {self.fairness.role_rot_window_days}")
        lines.append(f"workload_tolerance = {self.fairness.workload_tolerance}")
        lines.append("")
        lines.append("[weights]")
        lines.append(f"load_balance = {self.weights.load_balance}")
        lines.append(f"recency = {self.weights.recency}")
        lines.append(f"role_rotation = {self.weights.role_rotation}")
        lines.append(f"morning_pref = {self.weights.morning_pref}")
        lines.append(f"solene_bonus = {self.weights.solene_bonus}")
        lines.append("")
        lines.append("[packs]")
        for key in sorted(self.packs):
            roles = ", ".join(f'"{role}"' for role in self.packs[key])
            lines.append(f"{key} = [{roles}]")
        lines.append("")
        return "\n".join(lines)

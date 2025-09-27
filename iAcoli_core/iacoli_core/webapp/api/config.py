from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from ...config import FairnessConfig, GeneralConfig, WeightConfig
from ...errors import ValidationError
from ..container import ServiceContainer
from ..dependencies import get_container
from ..schemas import ConfigPayload, Message

router = APIRouter()


def _payload_from_config(container: ServiceContainer) -> ConfigPayload:
    cfg = container.config
    return ConfigPayload(
        general={
            "timezone": cfg.general.timezone,
            "default_view_days": cfg.general.default_view_days,
            "name_width": cfg.general.name_width,
            "overlap_minutes": cfg.general.overlap_minutes,
            "default_locale": cfg.general.default_locale,
        },
        fairness={
            "fair_window_days": cfg.fairness.fair_window_days,
            "role_rot_window_days": cfg.fairness.role_rot_window_days,
            "workload_tolerance": cfg.fairness.workload_tolerance,
        },
        weights={
            "load_balance": cfg.weights.load_balance,
            "recency": cfg.weights.recency,
            "role_rotation": cfg.weights.role_rotation,
            "morning_pref": cfg.weights.morning_pref,
            "solene_bonus": cfg.weights.solene_bonus,
        },
        packs=dict(sorted((int(key), list(value)) for key, value in cfg.packs.items())),
    )


@router.get("/", response_model=ConfigPayload)
def get_config(container: ServiceContainer = Depends(get_container)) -> ConfigPayload:
    return _payload_from_config(container)


@router.put("/", response_model=Message)
def update_config(payload: ConfigPayload, container: ServiceContainer = Depends(get_container)) -> Message:
    try:
        cfg = container.config.__class__(
            general=GeneralConfig(**payload.general.model_dump()),
            fairness=FairnessConfig(**payload.fairness.model_dump()),
            weights=WeightConfig(**payload.weights.model_dump()),
            packs={int(key): list(value) for key, value in payload.packs.items()},
        )
        cfg.validate()
        container.set_config(cfg, persist=True)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Message(detail="Configuracao atualizada.")


@router.post("/recarregar", response_model=Message)
def reload_config(container: ServiceContainer = Depends(get_container)) -> Message:
    container.reload_config()
    return Message(detail="Configuracao recarregada do arquivo.")


from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from ...agent import AgentOrchestrator
from ..container import ServiceContainer
from ..dependencies import get_container
from ..schemas import AgentInteractRequest, AgentInteractResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/interact", response_model=AgentInteractResponse, status_code=status.HTTP_200_OK)
def agent_interact(
    payload: AgentInteractRequest,
    container: ServiceContainer = Depends(get_container),
) -> AgentInteractResponse:
    orchestrator = AgentOrchestrator(container)
    try:
        result = orchestrator.interact(payload.prompt)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Agent orchestrator failed: %s", exc)
        raise HTTPException(status_code=500, detail="Erro interno ao processar o prompt.") from exc
    return AgentInteractResponse(**result)

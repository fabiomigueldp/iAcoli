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
    logger.info("=== NOVA REQUISICAO PARA /api/agent/interact ===")
    logger.info("[API] Prompt recebido: %s", payload.prompt)
    logger.debug("[API] Payload completo: %s", payload)
    
    try:
        logger.info("[API] Criando AgentOrchestrator")
        orchestrator = AgentOrchestrator(container)
        
        logger.info("[API] Iniciando interação com agente")
        result = orchestrator.interact(payload.prompt)
        
        logger.info("[API] Interação concluída com sucesso")
        logger.debug("[API] Resultado da interação: %s", result)
        
        response = AgentInteractResponse(**result)
        logger.info("[API] Resposta preparada, enviando para cliente")
        logger.debug("[API] Response object: %s", response)
        
        return response
        
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("[API] ERRO: Agent orchestrator falhou: %s", exc)
        raise HTTPException(status_code=500, detail="Erro interno ao processar o prompt.") from exc

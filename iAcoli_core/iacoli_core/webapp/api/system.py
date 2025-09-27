from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ...errors import ValidationError
from ..container import ServiceContainer
from ..dependencies import get_container
from ..schemas import Message, SaveStateResponse, StateLoadRequest, StateSaveRequest, UndoResponse

router = APIRouter()


@router.post("/salvar", response_model=SaveStateResponse)
def save_state(payload: StateSaveRequest, container: ServiceContainer = Depends(get_container)) -> SaveStateResponse:
    target = container.save_state(payload.path)
    return SaveStateResponse(path=str(target))


@router.post("/carregar", response_model=SaveStateResponse)
def load_state(payload: StateLoadRequest, container: ServiceContainer = Depends(get_container)) -> SaveStateResponse:
    try:
        target = container.load_state(payload.path)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SaveStateResponse(path=str(target))


@router.post("/undo", response_model=UndoResponse)
def undo(container: ServiceContainer = Depends(get_container)) -> UndoResponse:
    try:
        label = container.undo()
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not label:
        raise HTTPException(status_code=400, detail="Nada para desfazer.")
    return UndoResponse(message=container.localizer.text("undo.applied", label=label))



from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ... import errors
from ..container import ServiceContainer
from ..dependencies import get_container
from ..schemas import (
    AssignmentClearRequest,
    AssignmentRequest,
    AssignmentSwapRequest,
    CheckResult,
    FreeSlotEntry,
    Message,
    RecalculateRequest,
    ResetAssignmentsRequest,
    ScheduleEntry,
    StatsEntry,
    SuggestionEntry,
    SuggestionRequest,
)

router = APIRouter()


@router.get("/lista", response_model=List[ScheduleEntry])
def schedule_list(
    container: ServiceContainer = Depends(get_container),
    periodo: Optional[str] = Query(default=None),
    de: Optional[str] = Query(default=None),
    ate: Optional[str] = Query(default=None),
    communities: Optional[List[str]] = Query(default=None),
    roles: Optional[List[str]] = Query(default=None),
) -> List[ScheduleEntry]:
    rows = container.read(
        lambda: container.service.list_schedule(
            periodo=periodo,
            de=de,
            ate=ate,
            communities=communities,
            roles=roles,
        )
    )
    return [ScheduleEntry(**row) for row in rows]


@router.get("/livres", response_model=List[FreeSlotEntry])
def schedule_free(
    container: ServiceContainer = Depends(get_container),
    periodo: Optional[str] = Query(default=None),
    de: Optional[str] = Query(default=None),
    ate: Optional[str] = Query(default=None),
    communities: Optional[List[str]] = Query(default=None),
) -> List[FreeSlotEntry]:
    rows = container.read(
        lambda: container.service.list_free_slots(
            periodo=periodo,
            de=de,
            ate=ate,
            communities=communities,
        )
    )
    return [FreeSlotEntry(**row) for row in rows]


@router.post("/recalcular", response_model=Message)
def recalculate(payload: RecalculateRequest, container: ServiceContainer = Depends(get_container)) -> Message:
    container.mutate(
        container.service.recalculate,
        periodo=payload.periodo,
        de=payload.de,
        ate=payload.ate,
        seed=payload.seed,
    )
    return Message(detail=container.localizer.text("assignment.done"))


@router.post("/atribuir", response_model=Message, status_code=status.HTTP_201_CREATED)
def apply_assignment(payload: AssignmentRequest, container: ServiceContainer = Depends(get_container)) -> Message:
    try:
        container.mutate(
            container.service.apply_assignment,
            payload.event,
            payload.role,
            payload.person_id,
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Message(detail="Atribuicao aplicada.")


@router.post("/limpar", response_model=Message)
def clear_assignment(payload: AssignmentClearRequest, container: ServiceContainer = Depends(get_container)) -> Message:
    try:
        container.mutate(
            container.service.clear_assignment,
            payload.event,
            payload.role,
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Message(detail="Atribuicao removida.")


@router.post("/trocar", response_model=Message)
def swap_assignments(payload: AssignmentSwapRequest, container: ServiceContainer = Depends(get_container)) -> Message:
    try:
        container.mutate(
            container.service.swap_assignments,
            payload.event_a,
            payload.role_a,
            payload.event_b,
            payload.role_b,
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Message(detail="Atribuicoes trocadas.")


@router.post("/resetar", response_model=Message)
def reset_assignments(payload: ResetAssignmentsRequest, container: ServiceContainer = Depends(get_container)) -> Message:
    container.mutate(
        container.service.reset_assignments,
        periodo=payload.periodo,
        de=payload.de,
        ate=payload.ate,
    )
    return Message(detail="Atribuicoes reiniciadas.")


@router.get("/checagem", response_model=List[CheckResult])
def schedule_check(
    container: ServiceContainer = Depends(get_container),
    periodo: Optional[str] = Query(default=None),
    de: Optional[str] = Query(default=None),
    ate: Optional[str] = Query(default=None),
    communities: Optional[List[str]] = Query(default=None),
) -> List[CheckResult]:
    rows = container.read(
        lambda: container.service.check_schedule(
            periodo=periodo,
            de=de,
            ate=ate,
            communities=communities,
        )
    )
    return [CheckResult(**row) for row in rows]


@router.get("/estatisticas", response_model=List[StatsEntry])
def schedule_stats(
    container: ServiceContainer = Depends(get_container),
    periodo: Optional[str] = Query(default=None),
    de: Optional[str] = Query(default=None),
    ate: Optional[str] = Query(default=None),
    communities: Optional[List[str]] = Query(default=None),
) -> List[StatsEntry]:
    rows = container.read(
        lambda: container.service.stats(
            periodo=periodo,
            de=de,
            ate=ate,
            communities=communities,
        )
    )
    return [StatsEntry(**row) for row in rows]


@router.get("/sugestoes", response_model=List[SuggestionEntry])
def suggestions(
    container: ServiceContainer = Depends(get_container),
    event: str = Query(...),
    role: str = Query(...),
    top: int = Query(5, ge=1, le=20),
    seed: Optional[int] = Query(default=None),
) -> List[SuggestionEntry]:
    try:
        rows = container.read(
            lambda: container.service.suggest_candidates(
                event,
                role,
                top=top,
                seed=seed,
            )
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [SuggestionEntry(**row) for row in rows]


# Rotas alternativas em inglês para compatibilidade com a dashboard

@router.get("/", response_model=List[ScheduleEntry])
def schedule_list_en(
    container: ServiceContainer = Depends(get_container),
    periodo: Optional[str] = Query(default=None),
    de: Optional[str] = Query(default=None),
    ate: Optional[str] = Query(default=None),
    communities: Optional[List[str]] = Query(default=None),
    roles: Optional[List[str]] = Query(default=None),
) -> List[ScheduleEntry]:
    """Lista da escala atual (alias em inglês)."""
    return schedule_list(container, periodo, de, ate, communities, roles)


@router.post("/recalculate", response_model=Message)
def recalculate_en(payload: RecalculateRequest, container: ServiceContainer = Depends(get_container)) -> Message:
    """Recalcular escala (alias em inglês)."""
    return recalculate(payload, container)


@router.post("/assignments/apply", response_model=Message, status_code=status.HTTP_201_CREATED)
def apply_assignment_en(payload: AssignmentRequest, container: ServiceContainer = Depends(get_container)) -> Message:
    """Aplicar atribuição (alias em inglês)."""
    return apply_assignment(payload, container)


@router.post("/assignments/clear", response_model=Message)
def clear_assignment_en(payload: AssignmentClearRequest, container: ServiceContainer = Depends(get_container)) -> Message:
    """Limpar atribuição (alias em inglês)."""
    return clear_assignment(payload, container)


@router.post("/suggestions", response_model=List[SuggestionEntry])
def suggestions_en(payload: SuggestionRequest, container: ServiceContainer = Depends(get_container)) -> List[SuggestionEntry]:
    """Sugestões de candidatos (alias em inglês)."""
    try:
        rows = container.read(
            lambda: container.service.suggest_candidates(
                payload.event,
                payload.role,
                top=payload.top,
                seed=payload.seed,
            )
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [SuggestionEntry(**row) for row in rows]


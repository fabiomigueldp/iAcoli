from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ... import errors
from ...models import Recurrence, Series
from ..container import ServiceContainer
from ..dependencies import get_container
from ..schemas import (
    Message,
    RecurrenceCreate,
    RecurrenceOut,
    RecurrenceUpdate,
    SeriesCreate,
    SeriesOut,
    SeriesUpdate,
)

router = APIRouter()


def _series_to_out(item: Series) -> SeriesOut:
    return SeriesOut(
        id=item.id,
        base_event_id=item.base_event_id,
        days=item.days,
        kind=item.kind,
        pool=sorted(item.pool or [], key=str),
    )


def _recurrence_to_out(item: Recurrence) -> RecurrenceOut:
    return RecurrenceOut(
        id=item.id,
        community=item.community,
        dtstart_base=item.dtstart_base,
        rrule=item.rrule,
        quantity=item.quantity,
        pool=sorted(item.pool or [], key=str),
    )


@router.get("/", response_model=List[SeriesOut])
def list_series(container: ServiceContainer = Depends(get_container)) -> List[SeriesOut]:
    series = container.read(lambda: list(container.service.state.series.values()))
    return [_series_to_out(item) for item in series]


@router.post("/", response_model=SeriesOut, status_code=status.HTTP_201_CREATED)
def create_series(payload: SeriesCreate, container: ServiceContainer = Depends(get_container)) -> SeriesOut:
    try:
        item = container.mutate(
            container.service.create_series,
            base_event_id=payload.base_event_id,
            days=payload.days,
            kind=payload.kind,
            pool=payload.pool,
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _series_to_out(item)


@router.patch("/{series_id}", response_model=SeriesOut)
def update_series(series_id: UUID, payload: SeriesUpdate, container: ServiceContainer = Depends(get_container)) -> SeriesOut:
    if payload.new_base_event_id is None and payload.pool is None:
        raise HTTPException(status_code=400, detail="Nenhuma alteracao informada.")

    def action() -> Series:
        current = container.service.state.series.get(series_id)
        if not current:
            raise errors.ValidationError("Serie nao encontrada.")
        target_base = payload.new_base_event_id or current.base_event_id
        return container.service.rebase_series(
            series_id=series_id,
            new_base_event_id=target_base,
            pool=payload.pool,
        )

    try:
        item = container.mutate(action)
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _series_to_out(item)


@router.delete("/{series_id}", response_model=Message)
def remove_series(series_id: UUID, container: ServiceContainer = Depends(get_container)) -> Message:
    try:
        container.mutate(container.service.remove_series, series_id)
    except errors.ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Message(detail="Serie removida.")


@router.get("/recorrencias", response_model=List[RecurrenceOut])
def list_recurrences(container: ServiceContainer = Depends(get_container)) -> List[RecurrenceOut]:
    recurrences = container.read(lambda: list(container.service.state.recurrences.values()))
    return [_recurrence_to_out(item) for item in recurrences]


@router.post("/recorrencias", response_model=RecurrenceOut, status_code=status.HTTP_201_CREATED)
def create_recurrence(payload: RecurrenceCreate, container: ServiceContainer = Depends(get_container)) -> RecurrenceOut:
    try:
        item = container.mutate(
            container.service.create_recurrence,
            community=payload.community,
            dtstart_base=payload.dtstart_base,
            rrule=payload.rrule,
            quantity=payload.quantity,
            pool=payload.pool,
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _recurrence_to_out(item)


@router.patch("/recorrencias/{recurrence_id}", response_model=RecurrenceOut)
def update_recurrence(
    recurrence_id: UUID,
    payload: RecurrenceUpdate,
    container: ServiceContainer = Depends(get_container),
) -> RecurrenceOut:
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="Nenhuma alteracao informada.")
    try:
        item = container.mutate(
            container.service.update_recurrence,
            recurrence_id,
            rrule=data.get("rrule"),
            quantity=data.get("quantity"),
            pool=data.get("pool"),
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _recurrence_to_out(item)


@router.delete("/recorrencias/{recurrence_id}", response_model=Message)
def remove_recurrence(recurrence_id: UUID, container: ServiceContainer = Depends(get_container)) -> Message:
    try:
        container.mutate(container.service.remove_recurrence, recurrence_id)
    except errors.ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Message(detail="Recorrencia removida.")


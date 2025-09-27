from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ... import errors
from ...models import Event
from ..container import ServiceContainer
from ..dependencies import get_container
from ..schemas import (
    EventCreate,
    EventDetail,
    EventOut,
    EventUpdate,
    Message,
    PoolInfo,
    PoolUpdate,
)

router = APIRouter()


def _event_to_out(event: Event) -> EventOut:
    return EventOut(
        id=event.id,
        key=event.key(),
        community=event.community,
        dtstart=event.dtstart,
        dtend=event.dtend,
        quantity=event.quantity,
        kind=event.kind,
        pool=sorted(event.pool, key=str),
    )


@router.get("/", response_model=List[EventOut])
def list_events(
    container: ServiceContainer = Depends(get_container),
    community: Optional[List[str]] = Query(default=None),
    start: Optional[date] = Query(default=None),
    end: Optional[date] = Query(default=None),
) -> List[EventOut]:
    events = container.read(container.service.list_events)
    filtered: List[Event] = []
    for event in events:
        if community and event.community not in community:
            continue
        event_date = event.dtstart.date()
        if start and event_date < start:
            continue
        if end and event_date > end:
            continue
        filtered.append(event)
    return [_event_to_out(event) for event in filtered]


@router.post("/", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, container: ServiceContainer = Depends(get_container)) -> EventOut:
    try:
        event = container.mutate(
            container.service.create_event,
            community=payload.community,
            date_str=payload.date.isoformat(),
            time_str=payload.time.isoformat(timespec="minutes"),
            tz_name=container.config.general.timezone,
            quantity=payload.quantity,
            kind=payload.kind,
            pool=payload.pool,
            dtend=payload.dtend,
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _event_to_out(event)


@router.get("/{identifier}", response_model=EventDetail)
def get_event(identifier: str, container: ServiceContainer = Depends(get_container)) -> EventDetail:
    def fetch() -> EventDetail:
        event = container.service.get_event(identifier)
        assignments = container.service.state.assignments.get(event.id, {})
        people = container.service.state.people
        data = _event_to_out(event).model_dump()
        data["assignments"] = [
            {
                "role": role,
                "person_id": str(pid),
                "person_name": people.get(pid).name if people.get(pid) else None,
            }
            for role, pid in sorted(assignments.items())
        ]
        return EventDetail(**data)

    try:
        return container.read(fetch)
    except errors.ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{identifier}", response_model=EventOut)
def update_event(identifier: str, payload: EventUpdate, container: ServiceContainer = Depends(get_container)) -> EventOut:
    data = payload.model_dump(exclude_unset=True)
    try:
        event = container.mutate(
            container.service.update_event,
            identifier,
            community=data.get("community"),
            date_str=data["date"].isoformat() if "date" in data else None,
            time_str=data["time"].isoformat(timespec="minutes") if "time" in data else None,
            quantity=data.get("quantity"),
            kind=data.get("kind"),
            pool=data.get("pool"),
            tz_name=container.config.general.timezone,
            dtend=data.get("dtend"),
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _event_to_out(event)


@router.delete("/{identifier}", response_model=Message)
def remove_event(identifier: str, container: ServiceContainer = Depends(get_container)) -> Message:
    try:
        container.mutate(container.service.remove_event, identifier)
    except errors.ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Message(detail=container.localizer.text("event.removed"))


@router.get("/{identifier}/pool", response_model=PoolInfo)
def pool_info(identifier: str, container: ServiceContainer = Depends(get_container)) -> PoolInfo:
    try:
        info = container.read(lambda: container.service.pool_info(identifier))
    except errors.ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PoolInfo(**info)


@router.post("/{identifier}/pool", response_model=PoolInfo)
def set_pool(identifier: str, payload: PoolUpdate, container: ServiceContainer = Depends(get_container)) -> PoolInfo:
    try:
        container.mutate(container.service.set_pool, identifier, payload.members)
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return pool_info(identifier, container)


@router.delete("/{identifier}/pool", response_model=PoolInfo)
def clear_pool(identifier: str, container: ServiceContainer = Depends(get_container)) -> PoolInfo:
    try:
        container.mutate(container.service.clear_pool, identifier)
    except errors.ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return pool_info(identifier, container)


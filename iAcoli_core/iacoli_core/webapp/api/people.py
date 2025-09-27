from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ... import errors
from ...models import Availability, Person
from ..container import ServiceContainer
from ..dependencies import get_container
from ..schemas import (
    AvailabilityBlockIn,
    AvailabilityBlockOut,
    Message,
    PersonCreate,
    PersonDetail,
    PersonOut,
    PersonUpdate,
)

router = APIRouter()


def _person_to_schema(person: Person) -> PersonOut:
    return PersonOut(
        id=person.id,
        name=person.name,
        community=person.community,
        roles=sorted(person.roles),
        morning=person.morning,
        active=person.active,
        locale=person.locale,
    )


def _availability_to_schema(block: Availability) -> AvailabilityBlockOut:
    return AvailabilityBlockOut(start=block.start, end=block.end, note=block.note)


@router.get("/", response_model=List[PersonOut])
def list_people(container: ServiceContainer = Depends(get_container)) -> List[PersonOut]:
    people = container.read(container.service.list_people)
    return [_person_to_schema(person) for person in people]


@router.post("/", response_model=PersonOut, status_code=status.HTTP_201_CREATED)
def create_person(payload: PersonCreate, container: ServiceContainer = Depends(get_container)) -> PersonOut:
    try:
        person = container.mutate(
            container.service.add_person,
            name=payload.name,
            community=payload.community,
            roles=payload.roles,
            morning=payload.morning,
            active=payload.active,
            locale=payload.locale,
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _person_to_schema(person)


@router.get("/{person_id}", response_model=PersonDetail)
def person_detail(person_id: UUID, container: ServiceContainer = Depends(get_container)) -> PersonDetail:
    try:
        info = container.read(lambda: container.service.person_detail(person_id))
    except errors.ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    info["id"] = UUID(info["id"])
    return PersonDetail(**info)


@router.put("/{person_id}", response_model=PersonOut)
def update_person(person_id: UUID, payload: PersonUpdate, container: ServiceContainer = Depends(get_container)) -> PersonOut:
    data = payload.model_dump(exclude_unset=True)
    try:
        person = container.mutate(container.service.update_person, person_id, **data)
    except errors.ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _person_to_schema(person)


@router.delete("/{person_id}", response_model=Message)
def remove_person(person_id: UUID, container: ServiceContainer = Depends(get_container)) -> Message:
    try:
        container.mutate(container.service.remove_person, person_id)
    except errors.ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Message(detail=container.localizer.text("person.removed"))


@router.get("/{person_id}/blocks", response_model=List[AvailabilityBlockOut])
def list_blocks(person_id: UUID, container: ServiceContainer = Depends(get_container)) -> List[AvailabilityBlockOut]:
    try:
        blocks = container.read(lambda: container.service.list_blocks(person_id))
    except errors.ValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_availability_to_schema(block) for block in blocks]


@router.post("/{person_id}/blocks", response_model=Message, status_code=status.HTTP_201_CREATED)
def add_block(person_id: UUID, payload: AvailabilityBlockIn, container: ServiceContainer = Depends(get_container)) -> Message:
    try:
        container.mutate(
            container.service.add_block,
            person_id,
            start=payload.start,
            end=payload.end,
            note=payload.note,
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Message(detail="Bloqueio adicionado.")


@router.delete("/{person_id}/blocks", response_model=Message)
def remove_block(
    person_id: UUID,
    *,
    index: int | None = Query(default=None, ge=1),
    remove_all: bool = Query(default=False, alias="all"),
    container: ServiceContainer = Depends(get_container),
) -> Message:
    try:
        container.mutate(
            container.service.remove_block,
            person_id,
            index=index,
            remove_all=remove_all,
        )
    except errors.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Message(detail="Bloqueio removido.")


from __future__ import annotations

from datetime import date, datetime, time
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class PersonBase(BaseModel):
    name: str
    community: str
    roles: List[str] = Field(default_factory=list)
    morning: bool = False
    active: bool = True
    locale: Optional[str] = None


class PersonCreate(PersonBase):
    pass


class PersonUpdate(BaseModel):
    name: Optional[str] = None
    community: Optional[str] = None
    roles: Optional[List[str]] = None
    morning: Optional[bool] = None
    active: Optional[bool] = None
    locale: Optional[str] = None


class PersonOut(PersonBase):
    id: UUID


class AssignmentSummary(BaseModel):
    event: str
    community: str
    role: str
    date: str
    time: str


class PersonDetail(PersonOut):
    assignments: List[AssignmentSummary] = Field(default_factory=list)
    blocks: List[dict] = Field(default_factory=list)


class AvailabilityBlockIn(BaseModel):
    start: datetime
    end: datetime
    note: Optional[str] = None

    @field_validator("note")
    @classmethod
    def empty_to_none(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            return None
        return v


class AvailabilityBlockOut(BaseModel):
    start: datetime
    end: datetime
    note: Optional[str] = None


class EventBase(BaseModel):
    community: str
    date: date
    time: time
    quantity: int = Field(gt=0)
    kind: str = Field(default="REG")
    pool: Optional[List[UUID]] = None
    dtend: Optional[datetime] = None


class EventCreate(EventBase):
    pass


class EventUpdate(BaseModel):
    community: Optional[str] = None
    date: Optional[date] = None
    time: Optional[time] = None
    quantity: Optional[int] = Field(default=None, gt=0)
    kind: Optional[str] = None
    pool: Optional[List[UUID]] = None
    dtend: Optional[datetime] = None


class EventOut(BaseModel):
    id: UUID
    key: str
    community: str
    dtstart: datetime
    dtend: Optional[datetime]
    quantity: int
    kind: str
    pool: List[UUID] = Field(default_factory=list)


class EventAssignment(BaseModel):
    role: str
    person_id: Optional[str] = None
    person_name: Optional[str] = None


class EventDetail(EventOut):
    assignments: List[EventAssignment] = Field(default_factory=list)


class PoolInfo(BaseModel):
    event: str
    total: int
    members: List[dict]


class PoolUpdate(BaseModel):
    members: List[UUID] = Field(default_factory=list)


class SeriesCreate(BaseModel):
    base_event_id: UUID
    days: int
    kind: str
    pool: Optional[List[UUID]] = None


class SeriesUpdate(BaseModel):
    new_base_event_id: Optional[UUID] = None
    pool: Optional[List[UUID]] = None


class SeriesOut(BaseModel):
    id: UUID
    base_event_id: UUID
    days: int
    kind: str
    pool: List[UUID] = Field(default_factory=list)


class RecurrenceCreate(BaseModel):
    community: str
    dtstart_base: datetime
    rrule: str
    quantity: int
    pool: Optional[List[UUID]] = None


class RecurrenceUpdate(BaseModel):
    rrule: Optional[str] = None
    quantity: Optional[int] = None
    pool: Optional[List[UUID]] = None


class RecurrenceOut(BaseModel):
    id: UUID
    community: str
    dtstart_base: datetime
    rrule: str
    quantity: int
    pool: List[UUID] = Field(default_factory=list)


class ScheduleFilters(BaseModel):
    periodo: Optional[str] = None
    de: Optional[str] = None
    ate: Optional[str] = None
    communities: Optional[List[str]] = None
    roles: Optional[List[str]] = None


class ScheduleEntry(BaseModel):
    event: str
    community: str
    data: str
    hora: str
    role: str
    acolito: str
    person_id: Optional[str] = None


class FreeSlotEntry(BaseModel):
    event: str
    community: str
    data: str
    hora: str
    role: str


class SuggestionEntry(BaseModel):
    person_id: str
    nome: str
    com: str
    score: float
    overflow: float


class CheckResult(BaseModel):
    severity: str
    event: str
    issue: str


class StatsEntry(BaseModel):
    person_id: str
    nome: str
    com: str
    total: int
    roles: str


class AssignmentRequest(BaseModel):
    event: str
    role: str
    person_id: UUID


class AssignmentSwapRequest(BaseModel):
    event_a: str
    role_a: str
    event_b: str
    role_b: str


class AssignmentClearRequest(BaseModel):
    event: str
    role: str


class ResetAssignmentsRequest(BaseModel):
    periodo: Optional[str] = None
    de: Optional[str] = None
    ate: Optional[str] = None


class RecalculateRequest(BaseModel):
    periodo: Optional[str] = None
    de: Optional[str] = None
    ate: Optional[str] = None
    seed: Optional[int] = None


class SuggestionRequest(BaseModel):
    event: str
    role: str
    top: int = 5
    seed: Optional[int] = None


class ConfigGeneral(BaseModel):
    timezone: str
    default_view_days: int
    name_width: int
    overlap_minutes: int
    default_locale: str


class ConfigFairness(BaseModel):
    fair_window_days: int
    role_rot_window_days: int
    workload_tolerance: int


class ConfigWeights(BaseModel):
    load_balance: float
    recency: float
    role_rotation: float
    morning_pref: float
    solene_bonus: float


class ConfigPayload(BaseModel):
    general: ConfigGeneral
    fairness: ConfigFairness
    weights: ConfigWeights
    packs: dict[int, List[str]]


class Message(BaseModel):
    detail: str


class SaveStateResponse(BaseModel):
    path: str


class UndoResponse(BaseModel):
    message: str


class StateSaveRequest(BaseModel):
    path: Optional[str] = None


class StateLoadRequest(BaseModel):
    path: str



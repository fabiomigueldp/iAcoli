from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Dict, Mapping, Optional
from uuid import UUID

try:
    from uuid import uuid7 as _uuid7
except ImportError:
    from uuid import uuid4 as _uuid7


from .utils import isoformat, strip_diacritics, to_nfc

ROLE_CODES: tuple[str, ...] = (
    "LIB",
    "CRU",
    "MIC",
    "TUR",
    "NAV",
    "CER1",
    "CER2",
    "CAM",
)

ROLE_ALIASES: Dict[str, str] = {
    "CERO1": "CER1",
    "CERO2": "CER2",
    "CEROFERARIO1": "CER1",
    "CEROFERARIO2": "CER2",
    "CRUCIFERARIO": "CRU",
    "LIBRIFERO": "LIB",
    "MICROFONARIO": "MIC",
    "NAVETEIRO": "NAV",
    "TURIFERARIO": "TUR",
    "CAMPANARIO": "CAM",
}

COMMUNITY_ALIASES: Dict[str, str] = {
    "DIV": "DES",
}

COMMUNITIES: Dict[str, str] = {
    "MAT": "Matriz",
    "STM": "Sao Tiago Maior",
    "SJT": "Sao Judas Tadeu",
    "SJB": "Sao Joao Batista",
    "DES": "Divino Espirito Santo",
    "NSL": "Nossa Senhora de Lourdes",
}


def normalize_role(value: str) -> str:
    token = strip_diacritics(value.strip().upper())
    token = ROLE_ALIASES.get(token, token)
    if token not in ROLE_CODES:
        raise ValueError(f"Funcao desconhecida: {value}")
    return token


def normalize_roles(values) -> set[str]:
    return {normalize_role(value) for value in values}


def normalize_community(value: str) -> str:
    token = strip_diacritics(value.strip().upper())
    token = COMMUNITY_ALIASES.get(token, token)
    if token not in COMMUNITIES:
        raise ValueError(f"Comunidade desconhecida: {value}")
    return token


def new_id() -> UUID:
    return _uuid7()


@dataclass(slots=True)
class Availability:
    start: datetime
    end: datetime
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": isoformat(self.start),
            "end": isoformat(self.end),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Availability":
        return cls(
            start=datetime.fromisoformat(str(data["start"])),
            end=datetime.fromisoformat(str(data["end"])),
            note=data.get("note"),
        )


@dataclass(slots=True)
class Person:
    id: UUID
    name: str
    community: str
    roles: set[str] = field(default_factory=set)
    morning: bool = False
    active: bool = True
    locale: str | None = None

    def normalize(self) -> None:
        self.name = to_nfc(self.name.strip())
        self.community = normalize_community(self.community)
        self.roles = normalize_roles(self.roles)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "community": self.community,
            "roles": sorted(self.roles),
            "morning": self.morning,
            "active": self.active,
            "locale": self.locale,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Person":
        person = cls(
            id=UUID(str(data["id"])),
            name=str(data["name"]),
            community=str(data["community"]),
            roles=set(map(str, data.get("roles", []))),
            morning=bool(data.get("morning", False)),
            active=bool(data.get("active", True)),
            locale=data.get("locale"),
        )
        person.normalize()
        return person


@dataclass(slots=True)
class Event:
    id: UUID
    community: str
    dtstart: datetime
    quantity: int
    kind: str = "REG"
    dtend: datetime | None = None
    pool: set[UUID] | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.community = normalize_community(self.community)
        self.kind = self.kind.upper()
        if self.quantity < 1:
            raise ValueError("Quantidade deve ser positiva")
        if self.dtend and self.dtend < self.dtstart:
            raise ValueError("dtend antes do dtstart")
        if self.pool is None:
            self.pool = set()

    def key(self) -> str:
        return f"{self.community}{self.dtstart.strftime('%d%m%Y%H%M')}{self.quantity:03d}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "community": self.community,
            "dtstart": isoformat(self.dtstart),
            "dtend": isoformat(self.dtend) if self.dtend else None,
            "quantity": self.quantity,
            "kind": self.kind,
            "pool": [str(x) for x in sorted(self.pool or [], key=str)],
            "metadata": self.metadata or {},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Event":
        dtstart = datetime.fromisoformat(str(data["dtstart"]))
        dtend_raw = data.get("dtend")
        dtend = datetime.fromisoformat(dtend_raw) if dtend_raw else None
        pool = {UUID(x) for x in data.get("pool") or []}
        return cls(
            id=UUID(str(data["id"])),
            community=str(data["community"]),
            dtstart=dtstart,
            dtend=dtend,
            quantity=int(data.get("quantity", 1)),
            kind=str(data.get("kind", "REG")),
            pool=pool,
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(slots=True)
class Series:
    id: UUID
    base_event_id: UUID
    days: int
    kind: str
    pool: set[UUID] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "base_event_id": str(self.base_event_id),
            "days": self.days,
            "kind": self.kind,
            "pool": [str(x) for x in sorted(self.pool or [], key=str)],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Series":
        return cls(
            id=UUID(str(data["id"])),
            base_event_id=UUID(str(data["base_event_id"])),
            days=int(data.get("days", 0)),
            kind=str(data.get("kind", "REG")),
            pool={UUID(x) for x in data.get("pool") or []},
        )


@dataclass(slots=True)
class Recurrence:
    id: UUID
    community: str
    dtstart_base: datetime
    rrule: str
    quantity: int
    pool: set[UUID] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "community": self.community,
            "dtstart_base": isoformat(self.dtstart_base),
            "rrule": self.rrule,
            "quantity": self.quantity,
            "pool": [str(x) for x in sorted(self.pool or [], key=str)],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Recurrence":
        return cls(
            id=UUID(str(data["id"])),
            community=str(data["community"]),
            dtstart_base=datetime.fromisoformat(str(data["dtstart_base"])),
            rrule=str(data.get("rrule", "")),
            quantity=int(data.get("quantity", 1)),
            pool={UUID(x) for x in data.get("pool") or []},
        )


@dataclass(slots=True)
class State:
    people: Dict[UUID, Person] = field(default_factory=dict)
    events: Dict[UUID, Event] = field(default_factory=dict)
    series: Dict[UUID, Series] = field(default_factory=dict)
    recurrences: Dict[UUID, Recurrence] = field(default_factory=dict)
    assignments: Dict[UUID, Dict[str, UUID]] = field(default_factory=dict)
    availability: Dict[UUID, list[Availability]] = field(default_factory=dict)

    def clone(self) -> "State":
        return State(
            people={pid: replace(person) for pid, person in self.people.items()},
            events={eid: replace(event) for eid, event in self.events.items()},
            series={sid: replace(series) for sid, series in self.series.items()},
            recurrences={rid: replace(rec) for rid, rec in self.recurrences.items()},
            assignments={eid: dict(mapping) for eid, mapping in self.assignments.items()},
            availability={pid: list(blocks) for pid, blocks in self.availability.items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "people": [person.to_dict() for person in self.people.values()],
            "events": [event.to_dict() for event in self.events.values()],
            "series": [series.to_dict() for series in self.series.values()],
            "recurrences": [rec.to_dict() for rec in self.recurrences.values()],
            "assignments": [
                {"event_id": str(eid), "role": role, "person_id": str(pid)}
                for eid, mapping in self.assignments.items()
                for role, pid in mapping.items()
            ],
            "availability": [
                {
                    "person_id": str(pid),
                    "intervals": [block.to_dict() for block in blocks],
                }
                for pid, blocks in self.availability.items()
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "State":
        people = {person.id: person for person in (Person.from_dict(item) for item in data.get("people", []))}
        events = {event.id: event for event in (Event.from_dict(item) for item in data.get("events", []))}
        series = {serie.id: serie for serie in (Series.from_dict(item) for item in data.get("series", []))}
        recurrences = {rec.id: rec for rec in (Recurrence.from_dict(item) for item in data.get("recurrences", []))}
        assignments: Dict[UUID, Dict[str, UUID]] = {}
        for item in data.get("assignments", []):
            eid = UUID(str(item["event_id"]))
            role = str(item["role"])
            pid = UUID(str(item["person_id"]))
            assignments.setdefault(eid, {})[role] = pid
        availability: Dict[UUID, list[Availability]] = {}
        for entry in data.get("availability", []):
            pid = UUID(str(entry["person_id"]))
            availability[pid] = [Availability.from_dict(block) for block in entry.get("intervals", [])]
        return cls(
            people=people,
            events=events,
            series=series,
            recurrences=recurrences,
            assignments=assignments,
            availability=availability,
        )


DEFAULT_PACKS: Dict[int, list[str]] = {
    1: ["LIB"],
    2: ["LIB", "CRU"],
    3: ["LIB", "CRU", "MIC"],
    4: ["LIB", "CRU", "MIC", "TUR"],
    5: ["LIB", "CRU", "MIC", "TUR", "NAV"],
    6: ["LIB", "CRU", "MIC", "TUR", "NAV", "CAM"],
    7: ["LIB", "CRU", "MIC", "TUR", "NAV", "CER1", "CER2"],
    8: ["LIB", "CRU", "MIC", "TUR", "NAV", "CER1", "CER2", "CAM"],
}

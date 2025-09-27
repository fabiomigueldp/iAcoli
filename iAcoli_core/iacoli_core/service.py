from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence
from uuid import UUID

from .config import Config
from .errors import ConflictError, ValidationError
from .models import (
    Availability,
    Event,
    Person,
    Recurrence,
    Series,
    State,
    new_id,
    normalize_community,
    normalize_role,
)
from .repository import StateRepository
from .scheduler import Scheduler
from .utils import (
    build_period,
    combine_date_time,
    detect_timezone,
    parse_iso_date,
    parse_iso_time,
    strip_diacritics,
)


@dataclass(slots=True)
class EventView:
    id: UUID
    key: str
    community: str
    dtstart: datetime
    dtend: datetime | None
    quantity: int
    kind: str


class CoreService:
    def __init__(self, repository: StateRepository, config: Config) -> None:
        self.repository = repository
        self.config = config
        self.scheduler = Scheduler(config)

    # data access -----------------------------------------------------
    @property
    def state(self) -> State:
        return self.repository.state

    # people ----------------------------------------------------------
    def list_people(self) -> List[Person]:
        return sorted(self.state.people.values(), key=lambda person: strip_diacritics(person.name).upper())

    def get_person(self, person_id: UUID) -> Person:
        person = self.state.people.get(person_id)
        if not person:
            raise ValidationError("Acolito nao encontrado.")
        return person

    def add_person(
        self,
        *,
        name: str,
        community: str,
        roles: Sequence[str],
        morning: bool,
        active: bool,
        locale: str | None,
    ) -> Person:
        self.repository.push_history("person.add")
        pid = new_id()
        person = Person(
            id=pid,
            name=name,
            community=community,
            roles=set(roles),
            morning=morning,
            active=active,
            locale=locale,
        )
        person.normalize()
        self.state.people[pid] = person
        return person

    def update_person(
        self,
        person_id: UUID,
        *,
        name: str | None = None,
        community: str | None = None,
        roles: Sequence[str] | None = None,
        morning: bool | None = None,
        active: bool | None = None,
        locale: str | None = None,
    ) -> Person:
        person = self.get_person(person_id)
        self.repository.push_history("person.update")
        if name is not None:
            person.name = name
        if community is not None:
            person.community = community
        if roles is not None:
            person.roles = set(roles)
        if morning is not None:
            person.morning = morning
        if active is not None:
            person.active = active
        if locale is not None:
            person.locale = locale
        person.normalize()
        return person

    def remove_person(self, person_id: UUID) -> None:
        if person_id not in self.state.people:
            raise ValidationError("Acolito nao encontrado.")
        self.repository.push_history("person.remove")
        del self.state.people[person_id]
        for mapping in self.state.assignments.values():
            for role, pid in list(mapping.items()):
                if pid == person_id:
                    del mapping[role]
        self.state.availability.pop(person_id, None)

    def set_roles(self, person_id: UUID, roles: Sequence[str]) -> Person:
        person = self.get_person(person_id)
        self.repository.push_history("person.roles.set")
        person.roles = {normalize_role(role) for role in roles}
        return person

    def add_roles(self, person_id: UUID, roles: Sequence[str]) -> Person:
        person = self.get_person(person_id)
        self.repository.push_history("person.roles.add")
        person.roles |= {normalize_role(role) for role in roles}
        return person

    def remove_roles(self, person_id: UUID, roles: Sequence[str]) -> Person:
        person = self.get_person(person_id)
        self.repository.push_history("person.roles.del")
        for role in roles:
            person.roles.discard(normalize_role(role))
        return person

    def clear_roles(self, person_id: UUID) -> Person:
        person = self.get_person(person_id)
        self.repository.push_history("person.roles.clear")
        person.roles.clear()
        return person

    def list_blocks(self, person_id: UUID) -> List[Availability]:
        return sorted(self.state.availability.get(person_id, []), key=lambda item: item.start)

    def add_block(self, person_id: UUID, *, start: datetime, end: datetime, note: str | None) -> None:
        if end <= start:
            raise ValidationError("Fim do bloqueio deve ser posterior ao inicio.")
        self.repository.push_history("person.block")
        self.state.availability.setdefault(person_id, []).append(Availability(start=start, end=end, note=note))

    def remove_block(self, person_id: UUID, *, index: int | None, remove_all: bool) -> None:
        blocks = self.state.availability.get(person_id)
        if not blocks:
            raise ValidationError("Acolito nao possui bloqueios.")
        self.repository.push_history("person.unblock")
        if remove_all:
            blocks.clear()
            return
        if index is None or index < 1 or index > len(blocks):
            raise ValidationError("Indice invalido para desbloqueio.")
        blocks.pop(index - 1)

    def person_detail(self, person_id: UUID) -> dict:
        person = self.get_person(person_id)
        assignments: List[dict] = []
        for eid, mapping in self.state.assignments.items():
            event = self.state.events.get(eid)
            if not event:
                continue
            for role, pid in mapping.items():
                if pid != person_id:
                    continue
                assignments.append(
                    {
                        "event": event.key(),
                        "community": event.community,
                        "role": role,
                        "date": event.dtstart.date().isoformat(),
                        "time": event.dtstart.strftime("%H:%M"),
                    }
                )
        assignments.sort(key=lambda row: (row["date"], row["time"], row["role"]))
        return {
            "id": str(person.id),
            "name": person.name,
            "community": person.community,
            "roles": sorted(person.roles),
            "morning": person.morning,
            "active": person.active,
            "locale": person.locale,
            "assignments": assignments,
            "blocks": [block.to_dict() for block in self.list_blocks(person_id)],
        }

    # events -----------------------------------------------------------
    def list_events(self) -> List[Event]:
        return sorted(self.state.events.values(), key=lambda event: event.dtstart)

    def get_event(self, identifier: str) -> Event:
        try:
            uid = UUID(identifier)
            event = self.state.events.get(uid)
            if event:
                return event
        except ValueError:
            pass
        for event in self.state.events.values():
            if event.key() == identifier:
                return event
        raise ValidationError("Evento nao encontrado.")

    def create_event(
        self,
        *,
        community: str,
        date_str: str,
        time_str: str,
        tz_name: str,
        quantity: int,
        kind: str,
        pool: Sequence[UUID] | None,
        dtend: datetime | None = None,
    ) -> Event:
        tz = detect_timezone(tz_name)
        dtstart = combine_date_time(parse_iso_date(date_str), parse_iso_time(time_str), tz)
        self.repository.push_history("event.create")
        event = Event(
            id=new_id(),
            community=community,
            dtstart=dtstart,
            dtend=dtend,
            quantity=quantity,
            kind=kind,
            pool=set(pool or []),
        )
        self.state.events[event.id] = event
        return event

    def update_event(
        self,
        identifier: str,
        *,
        community: str | None,
        date_str: str | None,
        time_str: str | None,
        quantity: int | None,
        kind: str | None,
        pool: Sequence[UUID] | None,
        tz_name: str | None = None,
        dtend: datetime | None = None,
    ) -> Event:
        event = self.get_event(identifier)
        self.repository.push_history("event.update")
        tz = detect_timezone(tz_name or self.config.general.timezone)
        base_date = parse_iso_date(date_str) if date_str else event.dtstart.date()
        base_time = parse_iso_time(time_str) if time_str else event.dtstart.timetz()
        dtstart = combine_date_time(base_date, base_time, tz)
        updated = event.__class__(
            id=event.id,
            community=community or event.community,
            dtstart=dtstart,
            dtend=dtend if dtend is not None else event.dtend,
            quantity=quantity if quantity is not None else event.quantity,
            kind=kind if kind is not None else event.kind,
            pool=set(pool or event.pool or []),
            metadata=dict(event.metadata),
        )
        self.state.events[event.id] = updated
        return updated

    def remove_event(self, identifier: str) -> None:
        event = self.get_event(identifier)
        self.repository.push_history("event.remove")
        self.state.events.pop(event.id, None)
        self.state.assignments.pop(event.id, None)

    def set_pool(self, identifier: str, aids: Sequence[UUID]) -> Event:
        event = self.get_event(identifier)
        self.repository.push_history("event.pool")
        event.pool = set(aids)
        return event

    def clear_pool(self, identifier: str) -> Event:
        event = self.get_event(identifier)
        self.repository.push_history("event.pool.clear")
        event.pool = set()
        return event

    def pool_info(self, identifier: str) -> dict:
        event = self.get_event(identifier)
        members = []
        for pid in sorted(event.pool, key=str):
            person = self.state.people.get(pid)
            members.append(
                {
                    "person_id": str(pid),
                    "nome": person.name if person else "?",
                    "com": person.community if person else "?",
                }
            )
        return {
            "event": event.key(),
            "total": len(event.pool),
            "members": members,
        }

    # series / recurrences ---------------------------------------------
    def rebase_series(
        self,
        *,
        series_id: UUID,
        new_base_event_id: UUID,
        pool: Sequence[UUID] | None,
    ) -> Series:
        series = self.state.series.get(series_id)
        if not series:
            raise ValidationError('Serie nao encontrada.')
        if new_base_event_id not in self.state.events:
            raise ValidationError('Evento base nao encontrado.')
        self.repository.push_history('series.rebase')
        series.base_event_id = new_base_event_id
        if pool is not None:
            series.pool = set(pool)
        return series

    def create_series(
        self,
        *,
        base_event_id: UUID,
        days: int,
        kind: str,
        pool: Sequence[UUID] | None,
    ) -> Series:
        if base_event_id not in self.state.events:
            raise ValidationError("Evento base nao encontrado para serie.")
        self.repository.push_history("series.create")
        series = Series(id=new_id(), base_event_id=base_event_id, days=days, kind=kind, pool=set(pool or []))
        self.state.series[series.id] = series
        return series

    def remove_series(self, series_id: UUID) -> None:
        if series_id not in self.state.series:
            raise ValidationError("Serie nao encontrada.")
        self.repository.push_history("series.remove")
        del self.state.series[series_id]

    def create_recurrence(
        self,
        *,
        community: str,
        dtstart_base: datetime,
        rrule: str,
        quantity: int,
        pool: Sequence[UUID] | None,
    ) -> Recurrence:
        self.repository.push_history("recurrence.create")
        rec = Recurrence(
            id=new_id(),
            community=community,
            dtstart_base=dtstart_base,
            rrule=rrule,
            quantity=quantity,
            pool=set(pool or []),
        )
        self.state.recurrences[rec.id] = rec
        return rec

    def update_recurrence(
        self,
        recurrence_id: UUID,
        *,
        rrule: str | None,
        quantity: int | None,
        pool: Sequence[UUID] | None,
    ) -> Recurrence:
        rec = self.state.recurrences.get(recurrence_id)
        if not rec:
            raise ValidationError("Recorrencia nao encontrada.")
        self.repository.push_history("recurrence.update")
        rec.rrule = rrule or rec.rrule
        rec.quantity = quantity if quantity is not None else rec.quantity
        if pool is not None:
            rec.pool = set(pool)
        return rec

    def remove_recurrence(self, recurrence_id: UUID) -> None:
        if recurrence_id not in self.state.recurrences:
            raise ValidationError("Recorrencia nao encontrada.")
        self.repository.push_history("recurrence.remove")
        del self.state.recurrences[recurrence_id]

    # scheduling -------------------------------------------------------
    def recalculate(
        self,
        *,
        periodo: str | None,
        de: str | None,
        ate: str | None,
        seed: int | None,
    ) -> None:
        period = build_period(periodo, de, ate)
        events = self.list_events()
        if period:
            events = [event for event in events if period.contains(event.dtstart.date())]
        if not events:
            return
        self.repository.push_history("schedule.recalc")
        self.scheduler.recalculate(self.state, events=events, seed=seed)

    def list_schedule(
        self,
        *,
        periodo: str | None,
        de: str | None,
        ate: str | None,
        communities: Sequence[str] | None,
        roles: Sequence[str] | None,
    ) -> List[dict]:
        period = build_period(periodo, de, ate)
        rows: List[dict] = []
        for event in self.list_events():
            if period and not period.contains(event.dtstart.date()):
                continue
            if communities and event.community not in communities:
                continue
            assignment = self.state.assignments.get(event.id, {})
            for role, pid in assignment.items():
                if roles and role not in roles:
                    continue
                person = self.state.people.get(pid)
                rows.append(
                    {
                        "event": event.key(),
                        "community": event.community,
                        "data": event.dtstart.date().isoformat(),
                        "hora": event.dtstart.strftime("%H:%M"),
                        "role": role,
                        "acolito": person.name if person else "?",
                        "person_id": str(pid) if person else "",
                    }
                )
        rows.sort(key=lambda row: (row["data"], row["hora"], row["community"], row["role"]))
        return rows

    def list_free_slots(
        self,
        *,
        periodo: str | None,
        de: str | None,
        ate: str | None,
        communities: Sequence[str] | None,
    ) -> List[dict]:
        period = build_period(periodo, de, ate)
        rows: List[dict] = []
        for event in self.list_events():
            if period and not period.contains(event.dtstart.date()):
                continue
            if communities and event.community not in communities:
                continue
            required = self.scheduler.roles_for_quantity(event.quantity)
            assigned = self.state.assignments.get(event.id, {})
            pending = [role for role in required if role not in assigned]
            for role in pending:
                rows.append(
                    {
                        "event": event.key(),
                        "community": event.community,
                        "data": event.dtstart.date().isoformat(),
                        "hora": event.dtstart.strftime("%H:%M"),
                        "role": role,
                    }
                )
        rows.sort(key=lambda row: (row["data"], row["hora"], row["community"], row["role"]))
        return rows

    def suggest_candidates(
        self,
        identifier: str,
        role: str,
        *,
        top: int,
        seed: int | None,
    ) -> List[dict]:
        event = self.get_event(identifier)
        suggestions = self.scheduler.suggest(self.state, event=event, role=role, top=top, seed=seed)
        return [
            {
                "person_id": str(candidate.person.id),
                "nome": candidate.person.name,
                "com": candidate.person.community,
                "score": round(candidate.score, 3),
                "overflow": round(candidate.overflow, 3),
            }
            for candidate in suggestions
        ]

    def apply_assignment(self, identifier: str, role: str, person_id: UUID) -> None:
        event = self.get_event(identifier)
        person = self.get_person(person_id)
        if role not in person.roles:
            raise ValidationError("Acolito nao possui a funcao informada.")
        self.repository.push_history("assignment.apply")
        self.state.assignments.setdefault(event.id, {})[role] = person.id

    def clear_assignment(self, identifier: str, role: str) -> None:
        event = self.get_event(identifier)
        self.repository.push_history("assignment.clear")
        mapping = self.state.assignments.setdefault(event.id, {})
        mapping.pop(role, None)

    def swap_assignments(self, event_a: str, role_a: str, event_b: str, role_b: str) -> None:
        ev_a = self.get_event(event_a)
        ev_b = self.get_event(event_b)
        map_a = self.state.assignments.get(ev_a.id, {})
        map_b = self.state.assignments.get(ev_b.id, {})
        if role_a not in map_a or role_b not in map_b:
            raise ValidationError("Atribuicao inexistente para troca.")
        self.repository.push_history("assignment.swap")
        map_a[role_a], map_b[role_b] = map_b[role_b], map_a[role_a]

    def reset_assignments(self, *, periodo: str | None, de: str | None, ate: str | None) -> None:
        period = build_period(periodo, de, ate)
        self.repository.push_history("assignment.reset")
        if not period:
            self.state.assignments.clear()
            return
        for event in self.list_events():
            if period.contains(event.dtstart.date()):
                self.state.assignments.pop(event.id, None)

    def check_schedule(
        self,
        *,
        periodo: str | None,
        de: str | None,
        ate: str | None,
        communities: Sequence[str] | None,
    ) -> List[dict]:
        period = build_period(periodo, de, ate)
        overlap = timedelta(minutes=self.config.general.overlap_minutes)
        rows: List[dict] = []
        targeted_events = []
        for event in self.list_events():
            if period and not period.contains(event.dtstart.date()):
                continue
            if communities and event.community not in communities:
                continue
            targeted_events.append(event)
        person_events: Dict[UUID, List[Event]] = defaultdict(list)
        for event in targeted_events:
            required = self.scheduler.roles_for_quantity(event.quantity)
            assigned = self.state.assignments.get(event.id, {})
            for role in required:
                if role not in assigned:
                    rows.append(
                        {
                            "severity": "warn",
                            "event": event.key(),
                            "issue": f"Funcao {role} sem atribuicao",
                        }
                    )
            for role, pid in assigned.items():
                person = self.state.people.get(pid)
                if not person:
                    rows.append(
                        {
                            "severity": "error",
                            "event": event.key(),
                            "issue": f"Pessoa inexistente atribuida ({pid})",
                        }
                    )
                    continue
                if role not in person.roles:
                    rows.append(
                        {
                            "severity": "warn",
                            "event": event.key(),
                            "issue": f"{person.name} nao possui a funcao {role}",
                        }
                    )
                if not person.active:
                    rows.append(
                        {
                            "severity": "warn",
                            "event": event.key(),
                            "issue": f"{person.name} esta inativo",
                        }
                    )
                person_events[pid].append(event)
        for pid, ev_list in person_events.items():
            ev_list.sort(key=lambda event: event.dtstart)
            for idx in range(len(ev_list) - 1):
                current = ev_list[idx]
                nxt = ev_list[idx + 1]
                current_end = current.dtend or (current.dtstart + overlap)
                if current_end > nxt.dtstart:
                    person = self.state.people.get(pid)
                    rows.append(
                        {
                            "severity": "error",
                            "event": current.key(),
                            "issue": f"Choque com {nxt.key()} para {person.name if person else pid}",
                        }
                    )
        rows.sort(key=lambda row: (row["severity"], row["event"]))
        return rows

    def stats(
        self,
        *,
        periodo: str | None,
        de: str | None,
        ate: str | None,
        communities: Sequence[str] | None,
    ) -> List[dict]:
        period = build_period(periodo, de, ate)
        total_counter: Counter[UUID] = Counter()
        role_counter: Dict[UUID, Counter[str]] = defaultdict(Counter)
        for event in self.list_events():
            if period and not period.contains(event.dtstart.date()):
                continue
            if communities and event.community not in communities:
                continue
            for role, pid in self.state.assignments.get(event.id, {}).items():
                total_counter[pid] += 1
                role_counter[pid][role] += 1
        rows: List[dict] = []
        for pid, total in total_counter.items():
            person = self.state.people.get(pid)
            details = ", ".join(f"{role}:{count}" for role, count in sorted(role_counter[pid].items()))
            rows.append(
                {
                    "person_id": str(pid),
                    "nome": person.name if person else "?",
                    "com": person.community if person else "?",
                    "total": total,
                    "roles": details,
                }
            )
        rows.sort(key=lambda row: (-row["total"], strip_diacritics(row["nome"]).upper()))
        return rows

    # exports ----------------------------------------------------------
    def export_csv(
        self,
        *,
        path: Path,
        periodo: str | None,
        de: str | None,
        ate: str | None,
        communities: Sequence[str] | None,
        roles: Sequence[str] | None,
    ) -> Path:
        rows = self.list_schedule(periodo=periodo, de=de, ate=ate, communities=communities, roles=roles)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "time", "community", "event", "role", "person_id", "name"])
            for row in rows:
                writer.writerow(
                    [
                        row["data"],
                        row["hora"],
                        row["community"],
                        row["event"],
                        row["role"],
                        row.get("person_id", ""),
                        row.get("acolito", ""),
                    ]
                )
        return path

    def export_ics(
        self,
        *,
        path: Path,
        periodo: str | None,
        de: str | None,
        ate: str | None,
        communities: Sequence[str] | None,
        tz_name: str | None,
    ) -> Path:
        period = build_period(periodo, de, ate)
        events = []
        for event in self.list_events():
            if period and not period.contains(event.dtstart.date()):
                continue
            if communities and event.community not in communities:
                continue
            events.append(event)
        tzid = tz_name or self.config.general.timezone
        tz = detect_timezone(tzid)
        now_utc = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        lines: List[str] = []

        def add(line: str) -> None:
            lines.extend(self._fold_ics_line(line))

        add("BEGIN:VCALENDAR")
        add("VERSION:2.0")
        add("PRODID:-//iAcoli//Escala CLI 4.0//PT-BR")
        add("CALSCALE:GREGORIAN")
        add("METHOD:PUBLISH")

        offset = tz.utcoffset(datetime.now(tz)) or timedelta(0)
        for raw in [
            "BEGIN:VTIMEZONE",
            f"TZID:{tzid}",
            "BEGIN:STANDARD",
            "DTSTART:19700101T000000",
            f"TZOFFSETFROM:{self._format_offset(offset)}",
            f"TZOFFSETTO:{self._format_offset(offset)}",
            f"TZNAME:{tzid}",
            "END:STANDARD",
            "END:VTIMEZONE",
        ]:
            add(raw)

        for event in events:
            dtstart = event.dtstart.astimezone(tz)
            dtend = (event.dtend or (event.dtstart + timedelta(minutes=self.config.general.overlap_minutes))).astimezone(tz)
            assignments = self.state.assignments.get(event.id, {})
            description = "\n".join(
                f"{role}: {self.state.people.get(pid).name if self.state.people.get(pid) else pid}"
                for role, pid in sorted(assignments.items())
            ) or "Sem atribuicoes"
            add("BEGIN:VEVENT")
            add(f"UID:{event.id}@escala")
            add(f"DTSTAMP:{now_utc}")
            add(f"DTSTART;TZID={tzid}:{dtstart.strftime('%Y%m%dT%H%M%S')}")
            add(f"DTEND;TZID={tzid}:{dtend.strftime('%Y%m%dT%H%M%S')}")
            add(f"SUMMARY:{event.kind.title()} - {event.community}")
            add(f"DESCRIPTION:{self._escape_ics(description)}")
            add("END:VEVENT")

        add("END:VCALENDAR")
        payload = "\r\n".join(lines) + "\r\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return path

    @staticmethod
    def _format_offset(delta: timedelta) -> str:
        minutes = int(delta.total_seconds() // 60)
        sign = "+" if minutes >= 0 else "-"
        minutes = abs(minutes)
        hours, mins = divmod(minutes, 60)
        return f"{sign}{hours:02d}{mins:02d}"

    @staticmethod
    def _escape_ics(value: str) -> str:
        return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    @staticmethod
    def _fold_ics_line(line: str) -> List[str]:
        encoded = line.encode("utf-8")
        if len(encoded) <= 75:
            return [line]
        parts: List[str] = []
        while encoded:
            chunk = encoded[:75]
            encoded = encoded[75:]
            text = chunk.decode("utf-8", errors="ignore")
            parts.append(text)
        for idx in range(1, len(parts)):
            parts[idx] = " " + parts[idx]
        return parts

    # persistence ------------------------------------------------------
    def save_state(self, path: str | None = None) -> Path:
        target = Path(path) if path else self.repository.path
        self.repository.save(target)
        return target

    def load_state(self, path: str) -> Path:
        target = Path(path)
        self.repository.load(target)
        return target

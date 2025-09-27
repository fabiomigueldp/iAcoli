from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Dict, Iterable, List, Sequence
from uuid import UUID

from .config import Config
from .errors import ConflictError
from .models import Event, Person, State
from .utils import strip_diacritics

EXTRA_ROLE_ORDER: Sequence[str] = (
    "CER1",
    "CER2",
    "CRU",
    "MIC",
    "NAV",
    "CAM",
    "TUR",
    "LIB",
)


@dataclass(slots=True)
class Candidate:
    person: Person
    score: float
    overflow: float


class Scheduler:
    def __init__(self, config: Config) -> None:
        self.config = config

    def roles_for_quantity(self, quantity: int) -> List[str]:
        packs = self.config.packs
        if quantity in packs:
            return list(packs[quantity])
        possible = [key for key in packs if key <= quantity]
        if not possible:
            raise ConflictError("Nenhum pack configurado para a quantidade solicitada.")
        base_key = max(possible)
        roles = list(packs[base_key])
        idx = 0
        while len(roles) < quantity:
            roles.append(EXTRA_ROLE_ORDER[idx % len(EXTRA_ROLE_ORDER)])
            idx += 1
        return roles[:quantity]

    def recalculate(self, state: State, *, events: Iterable[Event], seed: int | None = None) -> None:
        assignment_index: Dict[UUID, List[tuple[datetime, str, UUID]]] = {}
        for eid, mapping in state.assignments.items():
            event = state.events.get(eid)
            if not event:
                continue
            for role, pid in mapping.items():
                assignment_index.setdefault(pid, []).append((event.dtstart, role, eid))
        for items in assignment_index.values():
            items.sort(key=lambda entry: entry[0])

        ordered_events = sorted(events, key=lambda ev: ev.dtstart)
        for event in ordered_events:
            existing = state.assignments.get(event.id, {})
            for role, pid in existing.items():
                records = assignment_index.get(pid)
                if records:
                    assignment_index[pid] = [item for item in records if item[2] != event.id]
            state.assignments[event.id] = {}

            required_roles = self.roles_for_quantity(event.quantity)
            for role in required_roles:
                candidate = self._pick_candidate(state, assignment_index, event, role, seed)
                state.assignments[event.id][role] = candidate.id
                assignment_index.setdefault(candidate.id, []).append((event.dtstart, role, event.id))
                assignment_index[candidate.id].sort(key=lambda entry: entry[0])

    def suggest(self, state: State, *, event: Event, role: str, top: int, seed: int | None = None) -> List[Candidate]:
        assignment_index: Dict[UUID, List[tuple[datetime, str, UUID]]] = {}
        for eid, mapping in state.assignments.items():
            ev = state.events.get(eid)
            if not ev:
                continue
            for role_name, pid in mapping.items():
                assignment_index.setdefault(pid, []).append((ev.dtstart, role_name, eid))
        for records in assignment_index.values():
            records.sort(key=lambda entry: entry[0])
        candidates = self._collect_candidates(state, assignment_index, event, role, seed)
        return candidates[:top]

    # internal helpers -------------------------------------------------

    def _pick_candidate(
        self,
        state: State,
        assignment_index: Dict[UUID, List[tuple[datetime, str, UUID]]],
        event: Event,
        role: str,
        seed: int | None,
    ) -> Person:
        candidates = self._collect_candidates(state, assignment_index, event, role, seed)
        if not candidates:
            raise ConflictError(f"Nenhum candidato disponivel para {role} em {event.key()}.")
        valid = [cand for cand in candidates if cand.overflow <= 0]
        if valid:
            ranked = sorted(
                valid,
                key=lambda cand: (
                    -cand.score,
                    strip_diacritics(cand.person.name).upper(),
                    str(cand.person.id),
                ),
            )
            return ranked[0].person
        fallback = sorted(
            candidates,
            key=lambda cand: (
                cand.overflow,
                -cand.score,
                strip_diacritics(cand.person.name).upper(),
                str(cand.person.id),
            ),
        )
        return fallback[0].person

    def _collect_candidates(
        self,
        state: State,
        assignment_index: Dict[UUID, List[tuple[datetime, str, UUID]]],
        event: Event,
        role: str,
        seed: int | None,
    ) -> List[Candidate]:
        fairness_window = timedelta(days=self.config.fairness.fair_window_days)
        role_window = timedelta(days=self.config.fairness.role_rot_window_days)
        overlap = timedelta(minutes=self.config.general.overlap_minutes)
        pool = event.pool or set(state.people.keys())
        candidates: List[Candidate] = []
        same_comm: List[Candidate] = []
        others: List[Candidate] = []

        counts_cache: Dict[UUID, List[tuple[datetime, str, UUID]]] = assignment_index
        community_counts: Dict[str, List[int]] = {}

        for pid in pool:
            person = state.people.get(pid)
            if not person or not person.active:
                continue
            if role not in person.roles:
                continue
            if not self._is_available(state, pid, event, overlap):
                continue
            if self._has_conflict(state, counts_cache, pid, event, overlap):
                continue
            stats = counts_cache.get(pid, [])
            load_count = self._count_in_window(stats, event.dtstart, fairness_window)
            community_counts.setdefault(role, [])
            community_counts[role].append(load_count)

        avg_load_map: Dict[UUID, float] = {}
        for pid in pool:
            person = state.people.get(pid)
            if not person or not person.active or role not in person.roles:
                continue
            stats = counts_cache.get(pid, [])
            load_count = self._count_in_window(stats, event.dtstart, fairness_window)
            avg_key = (event.community, role)
            if avg_key not in avg_load_map:
                loads = []
                for candidate_id in pool:
                    candidate = state.people.get(candidate_id)
                    if not candidate or role not in candidate.roles:
                        continue
                    candidate_stats = counts_cache.get(candidate_id, [])
                    loads.append(self._count_in_window(candidate_stats, event.dtstart, fairness_window))
                avg_load_map[avg_key] = mean(loads) if loads else 0.0

        for pid in pool:
            person = state.people.get(pid)
            if not person or not person.active:
                continue
            if role not in person.roles:
                continue
            if not self._is_available(state, pid, event, overlap):
                continue
            if self._has_conflict(state, counts_cache, pid, event, overlap):
                continue
            stats = counts_cache.get(pid, [])
            avg_load = avg_load_map.get((event.community, role), 0.0)
            load_count = self._count_in_window(stats, event.dtstart, fairness_window)
            overflow_limit = avg_load + self.config.fairness.workload_tolerance
            overflow = max(0.0, (load_count + 1) - overflow_limit)
            score = self._score_candidate(
                person=person,
                stats=stats,
                role=role,
                event=event,
                fairness_window=fairness_window,
                role_window=role_window,
                avg_load=avg_load,
                overflow=overflow,
                seed=seed,
            )
            candidate = Candidate(person=person, score=score, overflow=overflow)
            if person.community == event.community:
                same_comm.append(candidate)
            else:
                others.append(candidate)
        same_comm.sort(key=lambda cand: (-cand.score, strip_diacritics(cand.person.name).upper()))
        others.sort(key=lambda cand: (-cand.score, strip_diacritics(cand.person.name).upper()))
        candidates.extend(same_comm)
        candidates.extend(others)
        return candidates

    @staticmethod
    def _count_in_window(stats: Sequence[tuple[datetime, str, UUID]], ref: datetime, window: timedelta) -> int:
        lower = ref - window
        return sum(1 for dt, _role, _eid in stats if lower <= dt < ref)

    def _score_candidate(
        self,
        *,
        person: Person,
        stats: Sequence[tuple[datetime, str, UUID]],
        role: str,
        event: Event,
        fairness_window: timedelta,
        role_window: timedelta,
        avg_load: float,
        overflow: float,
        seed: int | None,
    ) -> float:
        load_component = self.config.weights.load_balance * (avg_load - overflow)
        recency_days = self._days_since_last(stats, event.dtstart)
        recency_component = self.config.weights.recency * recency_days
        role_gap = self._days_since_last_role(stats, event.dtstart, role)
        rotation_penalty = 0.0
        if role_gap < role_window.days:
            rotation_penalty = self.config.weights.role_rotation * (role_window.days - role_gap)
        morning_bonus = self.config.weights.morning_pref if event.dtstart.hour < 12 and person.morning else 0.0
        solene_bonus = self.config.weights.solene_bonus if event.kind == "SOLENE" else 0.0
        jitter = 0.0
        if seed is not None:
            jitter = (hash((seed, person.id.int)) % 1000) / 1_000_000.0
        return load_component + recency_component + rotation_penalty + morning_bonus + solene_bonus + jitter

    @staticmethod
    def _days_since_last(stats: Sequence[tuple[datetime, str, UUID]], ref: datetime) -> float:
        previous = [dt for dt, _role, _eid in stats if dt < ref]
        if not previous:
            return 365.0
        delta = ref - max(previous)
        return delta.days + delta.seconds / 86400

    @staticmethod
    def _days_since_last_role(stats: Sequence[tuple[datetime, str, UUID]], ref: datetime, role: str) -> float:
        previous = [dt for dt, role_name, _eid in stats if dt < ref and role_name == role]
        if not previous:
            return 365.0
        delta = ref - max(previous)
        return delta.days + delta.seconds / 86400

    def _is_available(self, state: State, person_id: UUID, event: Event, overlap: timedelta) -> bool:
        blocks = state.availability.get(person_id, [])
        start = event.dtstart
        end = event.dtend or (event.dtstart + overlap)
        for block in blocks:
            if block.end <= start or block.start >= end:
                continue
            return False
        return True

    def _has_conflict(
        self,
        state: State,
        assignment_index: Dict[UUID, List[tuple[datetime, str, UUID]]],
        person_id: UUID,
        event: Event,
        overlap: timedelta,
    ) -> bool:
        stats = assignment_index.get(person_id, [])
        start = event.dtstart
        end = event.dtend or (event.dtstart + overlap)
        for dt, _role, eid in stats:
            other = state.events.get(eid)
            if not other:
                continue
            other_start = other.dtstart
            other_end = other.dtend or (other.dtstart + overlap)
            if other_end <= start or other_start >= end:
                continue
            return True
        return False

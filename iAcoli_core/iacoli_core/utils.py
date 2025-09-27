from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Iterator, Sequence, TypeVar
from zoneinfo import ZoneInfo

from .errors import ValidationError

T = TypeVar("T")


def to_nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def strip_diacritics(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    filtered = [c for c in decomposed if not unicodedata.combining(c)]
    return unicodedata.normalize("NFC", "".join(filtered))


def detect_timezone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception as exc:  # pragma: no cover
        raise ValidationError(f"Fuso horario invalido: {tz_name}") from exc


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"Data invalida (use YYYY-MM-DD): {value}") from exc


def parse_iso_time(value: str) -> time:
    try:
        if len(value) == 5 and value.count(":") == 1:
            return time.fromisoformat(value)
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"Hora invalida (use HH:MM): {value}") from exc


def combine_date_time(d: date, t: time, tzinfo: ZoneInfo) -> datetime:
    base = datetime.combine(d, t)
    if base.tzinfo is None:
        base = base.replace(tzinfo=tzinfo)
    return base.astimezone(tzinfo)


def ensure_tzaware(dt: datetime, tzinfo: ZoneInfo) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tzinfo)
    return dt.astimezone(tzinfo)


def isoformat(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ""


def parse_rfc3339(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"Timestamp invalido (RFC 3339): {value}") from exc


def human_duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h{mins:02d}"
    if hours:
        return f"{hours}h"
    return f"{mins}min"


def seeded_shuffle(seq: Sequence[T], seed: int | None) -> list[T]:
    data = list(seq)
    if seed is None:
        return data
    rng = random.Random(seed)
    rng.shuffle(data)
    return data


def stable_sorted(items: Iterable[T], *, key=None) -> list[T]:
    return sorted(items, key=key)


@dataclass(slots=True)
class Period:
    start: date
    end: date

    def contains(self, target: date) -> bool:
        return self.start <= target <= self.end


def build_period(periodo: str | None, de: str | None, ate: str | None) -> Period | None:
    if periodo:
        if de or ate:
            raise ValidationError("Use apenas --periodo ou --de/--ate.")
        try:
            year_str, month_str = periodo.split("-", 1)
            year = int(year_str)
            month = int(month_str)
            start = date(year, month, 1)
        except Exception as exc:
            raise ValidationError("Periodo invalido (use YYYY-MM).") from exc
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        return Period(start, end)
    if de or ate:
        if not (de and ate):
            raise ValidationError("Use --de e --ate juntos.")
        start = parse_iso_date(de)
        end = parse_iso_date(ate)
        if end < start:
            raise ValidationError("Intervalo invalido: fim antes do inicio.")
        return Period(start, end)
    return None


def chunked(seq: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for idx in range(0, len(seq), size):
        yield seq[idx : idx + size]


def comma_split(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [token.strip() for token in raw.split(',') if token.strip()]

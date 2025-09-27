from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from .errors import IOErrorWithCode, ValidationError
from .models import State

STATE_FILE_DEFAULT = Path("state.json")


@dataclass(slots=True)
class Snapshot:
    label: str
    timestamp: datetime
    state: State


class StateRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or STATE_FILE_DEFAULT
        self.state: State = State()
        self.history: List[Snapshot] = []
        if self.path.exists():
            self.load()

    def load(self, path: Path | None = None) -> None:
        target = path or self.path
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise IOErrorWithCode(f"Arquivo nao encontrado: {target}") from exc
        except json.JSONDecodeError as exc:
            raise IOErrorWithCode(f"JSON invalido em {target}: {exc}") from exc
        self.state = State.from_dict(payload)
        self.path = target

    def save(self, path: Path | None = None) -> None:
        target = path or self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self.state.to_dict(), indent=2, ensure_ascii=False)
        target.write_text(data, encoding="utf-8")
        self.path = target

    def push_history(self, label: str) -> None:
        snapshot = Snapshot(label=label, timestamp=datetime.utcnow(), state=self.state.clone())
        self.history.append(snapshot)
        if len(self.history) > 64:
            self.history.pop(0)

    def undo(self) -> Snapshot:
        if not self.history:
            raise ValidationError("Nada para desfazer.")
        snapshot = self.history.pop()
        self.state = snapshot.state.clone()
        return snapshot

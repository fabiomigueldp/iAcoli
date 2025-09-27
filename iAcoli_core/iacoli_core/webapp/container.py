from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Optional, TypeVar

from ..config import Config, DEFAULT_CONFIG_PATH
from ..localization import Localizer
from ..repository import StateRepository
from ..service import CoreService

T = TypeVar("T")

DEFAULT_STATE_PATH = Path("state.json")


@dataclass(slots=True)
class ContainerSettings:
    config_path: Path = DEFAULT_CONFIG_PATH
    state_path: Path = DEFAULT_STATE_PATH
    auto_save: bool = True


class ServiceContainer:
    """Mantem instancias compartilhadas de configuracao, repositorio e servico."""

    def __init__(
        self,
        config_path: Path | str | None = None,
        state_path: Path | str | None = None,
        *,
        auto_save: bool = True,
    ) -> None:
        cfg_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        st_path = Path(state_path) if state_path else DEFAULT_STATE_PATH
        self.settings = ContainerSettings(config_path=cfg_path, state_path=st_path, auto_save=auto_save)
        self._lock = RLock()
        self.config: Config
        self.repo: StateRepository
        self.service: CoreService
        self.localizer: Localizer
        self._initialise()

    def _initialise(self) -> None:
        config = Config.load(path=self.settings.config_path)
        repo = StateRepository(self.settings.state_path)
        service = CoreService(repo, config)
        self.config = config
        self.repo = repo
        self.service = service
        self.localizer = Localizer(config.general.default_locale)

    @property
    def config_path(self) -> Path:
        return self.settings.config_path

    @property
    def state_path(self) -> Path:
        return self.settings.state_path

    def read(self, func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        with self._lock:
            return func(*args, **kwargs)

    def mutate(self, func: Callable[..., T], /, *args: Any, auto_save: Optional[bool] = None, **kwargs: Any) -> T:
        with self._lock:
            result = func(*args, **kwargs)
            should_save = self.settings.auto_save if auto_save is None else auto_save
            if should_save:
                self.repo.save(self.settings.state_path)
            return result

    def save_state(self, path: Path | str | None = None) -> Path:
        with self._lock:
            target = self.service.save_state(str(path) if path else None)
            self.settings.state_path = target
            return target

    def load_state(self, path: Path | str) -> Path:
        target = Path(path)
        with self._lock:
            loaded = self.service.load_state(str(target))
            self.settings.state_path = loaded
            return loaded

    def reload_config(self) -> Config:
        with self._lock:
            cfg = Config.load(path=self.settings.config_path)
            self._apply_config(cfg, persist=False)
            return cfg

    def set_config(self, config: Config, *, persist: bool = True) -> None:
        with self._lock:
            self._apply_config(config, persist=persist)

    def _apply_config(self, config: Config, *, persist: bool) -> None:
        self.config = config
        self.service = CoreService(self.repo, config)
        self.localizer = Localizer(config.general.default_locale)
        if persist:
            self.settings.config_path.write_text(config.to_toml(), encoding="utf-8")

    def undo(self) -> Optional[str]:
        with self._lock:
            snapshot = self.repo.undo()
            self.repo.save(self.settings.state_path)
            return snapshot.label


__all__ = ["ServiceContainer", "ContainerSettings", "DEFAULT_STATE_PATH"]

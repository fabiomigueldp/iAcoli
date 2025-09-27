from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

DEFAULT_LOCALE = "pt-BR"


MESSAGES: Mapping[str, Mapping[str, str]] = {
    "pt-BR": {
        "person.added": "[OK] Acolito adicionado.",
        "person.updated": "[EDIT] Dados do acolito atualizados.",
        "person.removed": "[DEL] Acolito removido.",
        "event.created": "[OK] Evento criado.",
        "event.updated": "[EDIT] Evento atualizado.",
        "event.removed": "[DEL] Evento removido.",
        "assignment.done": "[OK] Escala recalculada.",
        "state.saved": "[SAVE] Estado salvo em {path}.",
        "state.loaded": "[LOAD] Estado carregado de {path}.",
        "undo.applied": "[UNDO] Restauracao aplicada ({label}).",
        "undo.empty": "[ERR] Nada para desfazer.",
    },
    "en-US": {
        "person.added": "[OK] Member added.",
        "person.updated": "[EDIT] Member updated.",
        "person.removed": "[DEL] Member removed.",
        "event.created": "[OK] Event created.",
        "event.updated": "[EDIT] Event updated.",
        "event.removed": "[DEL] Event removed.",
        "assignment.done": "[OK] Schedule recalculated.",
        "state.saved": "[SAVE] State saved to {path}.",
        "state.loaded": "[LOAD] State loaded from {path}.",
        "undo.applied": "[UNDO] Restore applied ({label}).",
        "undo.empty": "[ERR] Nothing to undo.",
    },
}


@dataclass(slots=True)
class Localizer:
    locale: str = DEFAULT_LOCALE

    def text(self, key: str, **kwargs) -> str:
        table = MESSAGES.get(self.locale, MESSAGES[DEFAULT_LOCALE])
        template = table.get(key, key)
        if kwargs:
            return template.format(**kwargs)
        return template

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class EscalaError(Exception):
    message: str
    code: int

    def __str__(self) -> str:  # pragma: no cover
        return self.message


class UsageError(EscalaError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 2)


class ValidationError(EscalaError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 3)


class ConflictError(EscalaError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 4)


class IOErrorWithCode(EscalaError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 5)


class InternalError(EscalaError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 6)

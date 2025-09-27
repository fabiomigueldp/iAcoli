from fastapi import Request

from .container import ServiceContainer
from ..service import CoreService


def get_container(request: Request) -> ServiceContainer:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, ServiceContainer):
        raise RuntimeError("ServiceContainer nao configurado no app.")
    return container


def get_service(request: Request) -> CoreService:
    container = get_container(request)
    return container.service

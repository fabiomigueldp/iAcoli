# iacoli_core/webapp/dashboard.py
"""Rotas da dashboard web do iAcoli Core."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .container import ServiceContainer
from .dependencies import get_container

router = APIRouter()


def get_templates(request: Request) -> Jinja2Templates:
    """Obtém instância de templates do app state."""
    return request.app.state.templates


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    container: ServiceContainer = Depends(get_container)
) -> Any:
    """Página principal da dashboard."""
    # Dados básicos para a dashboard
    people = container.read(container.service.list_people)
    events = container.read(container.service.list_events)
    
    context = {
        "request": request,
        "title": "iAcoli Core - Dashboard",
        "people_count": len(people),
        "events_count": len(events),
        "active_people": len([p for p in people if p.active]),
    }
    
    return templates.TemplateResponse("dashboard/home.html", context)


@router.get("/people", response_class=HTMLResponse)
async def dashboard_people(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    container: ServiceContainer = Depends(get_container)
) -> Any:
    """Página de gerenciamento de pessoas."""
    people = container.read(container.service.list_people)
    
    context = {
        "request": request,
        "title": "Gerenciar Pessoas",
        "people": people,
    }
    
    return templates.TemplateResponse("dashboard/people.html", context)


@router.get("/events", response_class=HTMLResponse)
async def dashboard_events(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    container: ServiceContainer = Depends(get_container)
) -> Any:
    """Página de gerenciamento de eventos."""
    events = container.read(container.service.list_events)
    
    context = {
        "request": request,
        "title": "Gerenciar Eventos",
        "events": events,
    }
    
    return templates.TemplateResponse("dashboard/events.html", context)


@router.get("/schedule", response_class=HTMLResponse)
async def dashboard_schedule(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    container: ServiceContainer = Depends(get_container)
) -> Any:
    """Página de visualização de escala."""
    # Chamar list_schedule com parâmetros padrão (todos None = mostrar tudo)
    schedule = container.read(lambda: container.service.list_schedule(
        periodo=None,
        de=None,
        ate=None,
        communities=None,
        roles=None
    ))
    
    context = {
        "request": request,
        "title": "Escala Atual",
        "schedule": schedule,
    }
    
    return templates.TemplateResponse("dashboard/schedule.html", context)


@router.get("/config", response_class=HTMLResponse)
async def dashboard_config(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    container: ServiceContainer = Depends(get_container)
) -> Any:
    """Página de configurações."""
    config = container.config
    
    context = {
        "request": request,
        "title": "Configurações",
        "config": config,
    }
    
    return templates.TemplateResponse("dashboard/config.html", context)
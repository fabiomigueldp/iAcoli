# iacoli_core/webapp/app.py
from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .api import router as api_router
from .dashboard import router as dashboard_router
from .container import ServiceContainer, DEFAULT_STATE_PATH
from ..config import DEFAULT_CONFIG_PATH


def create_app(
    *,
    config_path: str | None = None,
    state_path: str | None = None,
    auto_save: bool = True,
) -> FastAPI:
    """Cria uma aplicação FastAPI configurada com o iAcoli Core."""
    app = FastAPI(
        title="iAcoli Core API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        description="API para gerenciamento de escalas e eventos",
    )

    # Middleware CORS (ajuste origens conforme sua necessidade)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Em produção, especifique as origens permitidas
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    # Middleware GZip para respostas maiores (calendários ICS, CSV)
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    # Container compartilhado (thread-safe via RLock)
    container = ServiceContainer(
        config_path=config_path or str(DEFAULT_CONFIG_PATH),
        state_path=state_path or str(DEFAULT_STATE_PATH),
        auto_save=auto_save,
    )
    app.state.container = container

    # Configuração de templates e arquivos estáticos
    webapp_dir = Path(__file__).parent
    templates_dir = webapp_dir / "templates"
    static_dir = webapp_dir / "static"
    
    # Montar arquivos estáticos
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    
    # Configurar templates
    if templates_dir.exists():
        app.state.templates = Jinja2Templates(directory=str(templates_dir))

    # Rotas
    app.include_router(api_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/dashboard")

    @app.get("/health")
    def health() -> dict[str, str]:
        """Endpoint de verificação de saúde da aplicação."""
        return {"status": "ok", "message": "iAcoli Core API está funcionando"}

    @app.get("/")
    def root():
        """Redireciona para a dashboard."""
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/dashboard/", status_code=302)

    return app


# Instância padrão para "uvicorn iacoli_core.webapp.app:app"
app = create_app()
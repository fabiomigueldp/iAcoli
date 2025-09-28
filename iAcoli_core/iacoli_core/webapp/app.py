# iacoli_core/webapp/app.py
from __future__ import annotations

import os
import logging
import time
from pathlib import Path
from fastapi import FastAPI, Request, Response

# Carrega as variáveis de ambiente do arquivo .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Se python-dotenv não estiver instalado, tenta carregar manualmente
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.strip().startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value
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
    
    # Configurar logging para transparência total
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()  # Console handler para uvicorn
        ]
    )
    
    # Logger específico para a aplicação
    app_logger = logging.getLogger("iacoli_webapp")
    app_logger.info("=== INICIANDO IACOLI CORE WEBAPP ===")
    
    app = FastAPI(
        title="iAcoli Core API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        description="API para gerenciamento de escalas e eventos",
    )
    
    # Middleware para logging de todas as requisições
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.time()
        
        # Log da requisição
        app_logger.info("=== NOVA REQUISICAO ===")
        app_logger.info("[HTTP] %s %s", request.method, request.url)
        app_logger.info("[HTTP] Headers: %s", dict(request.headers))
        
        # Se houver body, tenta logar (apenas para debugging)
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                if body:
                    app_logger.debug("[HTTP] Body: %s", body.decode("utf-8")[:1000])
            except:
                app_logger.debug("[HTTP] Body não pôde ser lido")
        
        # Processa a requisição
        response = await call_next(request)
        
        # Log da resposta
        duration = time.time() - start_time
        app_logger.info("[HTTP] Resposta: %d - %s", response.status_code, 
                       response.headers.get("content-type", "unknown"))
        app_logger.info("[HTTP] Duração: %.3f segundos", duration)
        
        return response

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
    app_logger.info("[INIT] Configurando ServiceContainer")
    app_logger.info("[INIT] Config path: %s", config_path or str(DEFAULT_CONFIG_PATH))
    app_logger.info("[INIT] State path: %s", state_path or str(DEFAULT_STATE_PATH))
    app_logger.info("[INIT] Auto save: %s", auto_save)
    
    container = ServiceContainer(
        config_path=config_path or str(DEFAULT_CONFIG_PATH),
        state_path=state_path or str(DEFAULT_STATE_PATH),
        auto_save=auto_save,
    )
    app.state.container = container
    app_logger.info("[INIT] ServiceContainer configurado com sucesso")

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
    app_logger.info("[INIT] Configurando rotas da API")
    app.include_router(api_router, prefix="/api")
    app_logger.info("[INIT] Rotas da API configuradas: /api/*")
    
    app.include_router(dashboard_router, prefix="/dashboard")
    app_logger.info("[INIT] Rotas do dashboard configuradas: /dashboard/*")

    @app.get("/health")
    def health() -> dict[str, str]:
        """Endpoint de verificação de saúde da aplicação."""
        app_logger.info("[HEALTH] Health check solicitado")
        return {"status": "ok", "message": "iAcoli Core API está funcionando"}

    @app.get("/")
    def root():
        """Redireciona para a dashboard."""
        app_logger.info("[ROOT] Redirecionamento para dashboard solicitado")
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/dashboard/", status_code=302)

    app_logger.info("=== IACOLI CORE WEBAPP INICIALIZADO COM SUCESSO ===")
    return app


# Instância padrão para "uvicorn iacoli_core.webapp.app:app"
app = create_app()
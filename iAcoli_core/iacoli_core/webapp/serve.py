# iacoli_core/webapp/serve.py
"""Script para executar o servidor web do iAcoli Core."""

import uvicorn


def main() -> None:
    """Inicia o servidor web do iAcoli Core."""
    uvicorn.run(
        "iacoli_core.webapp.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
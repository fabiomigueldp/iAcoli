#!/usr/bin/env python3
"""
Script para iniciar o servidor iAcoli Core com facilidade.

Este script carrega automaticamente as variáveis do arquivo .env
e inicia o servidor uvicorn na porta 8000.

Uso:
    python run.py
"""

import os
import sys
from pathlib import Path

# Adiciona o diretório do projeto ao Python path
project_dir = Path(__file__).parent
sys.path.insert(0, str(project_dir))

# Carrega as variáveis de ambiente do arquivo .env
try:
    from dotenv import load_dotenv
    load_dotenv(project_dir / ".env")
    print("✅ Variáveis de ambiente carregadas do arquivo .env")
except ImportError:
    print("⚠️  python-dotenv não encontrado, tentando carregar .env manualmente...")
    env_path = project_dir / ".env"
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                if '=' in line and not line.strip().startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value
        print("✅ Variáveis de ambiente carregadas manualmente")
    else:
        print("❌ Arquivo .env não encontrado")

# Verifica se a chave da Perplexity está configurada
if not os.environ.get("PPLX_API_KEY"):
    print("❌ ERRO: PPLX_API_KEY não está configurada!")
    print("📝 Configure a chave no arquivo .env")
    sys.exit(1)
else:
    pplx_key = os.environ.get("PPLX_API_KEY")
    print(f"✅ PPLX_API_KEY configurada: {pplx_key[:12]}...{pplx_key[-4:]}")

if __name__ == "__main__":
    print("\n🚀 Iniciando servidor iAcoli Core...")
    print("📍 URL: http://localhost:8000")
    print("📍 Dashboard: http://localhost:8000/dashboard")
    print("📍 API Docs: http://localhost:8000/docs")
    print("📍 Para parar: Ctrl+C\n")
    
    # Importa e executa o servidor
    try:
        import uvicorn
        uvicorn.run(
            "iacoli_core.webapp.app:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info",
            access_log=True
        )
    except ImportError:
        print("❌ ERRO: uvicorn não está instalado!")
        print("💡 Instale com: pip install uvicorn")
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERRO ao iniciar servidor: {e}")
        sys.exit(1)
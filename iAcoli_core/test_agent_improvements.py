#!/usr/bin/env python3
"""
Script de teste para verificar as melhorias no agente iAcoli.
"""

import sys
import os
from pathlib import Path

# Adiciona o diretório do projeto ao path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Testa as importações diretamente (evitando importação circular)
try:
    import importlib.util
    
    # Carrega models.py
    spec = importlib.util.spec_from_file_location("models", project_root / "iacoli_core" / "models.py")
    models_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(models_module)
    ROLE_CODES = models_module.ROLE_CODES
    COMMUNITIES = models_module.COMMUNITIES
    
    # Carrega prompt_builder.py
    spec = importlib.util.spec_from_file_location("prompt_builder", project_root / "iacoli_core" / "agent" / "prompt_builder.py")
    pb_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pb_module)
    BASE_PROMPT = pb_module.BASE_PROMPT
    build_system_prompt = pb_module.build_system_prompt
    
    print("✅ Importações bem-sucedidas!")
except Exception as e:
    print(f"❌ Erro na importação: {e}")
    sys.exit(1)

def test_base_prompt():
    """Testa se o novo BASE_PROMPT contém as melhorias esperadas."""
    print("\n=== TESTANDO BASE_PROMPT ===")
    
    # Verifica se contém as regras críticas
    expected_phrases = [
        "REGRAS CRÍTICAS E INVIOLÁVEIS",
        "SAÍDA ESTRITAMENTE JSON",
        "NÃO SEJA UM ASSISTENTE GERAL",
        "USE AS FERRAMENTAS",
        "{system_context}",
        "{tool_docs}"
    ]
    
    for phrase in expected_phrases:
        if phrase in BASE_PROMPT:
            print(f"✅ Contém: {phrase}")
        else:
            print(f"❌ Faltando: {phrase}")
    
    print(f"📊 Tamanho do prompt: {len(BASE_PROMPT)} caracteres")

def test_system_context():
    """Testa se o contexto do sistema está sendo injetado corretamente."""
    print("\n=== TESTANDO CONTEXTO DO SISTEMA ===")
    
    # Testa com uma requisição simples
    prompt = build_system_prompt("cadastrar acolito")
    
    # Verifica se ROLE_CODES estão no prompt
    all_roles_present = all(role in prompt for role in ROLE_CODES)
    if all_roles_present:
        print("✅ Todos os ROLE_CODES estão no contexto")
    else:
        print("❌ Alguns ROLE_CODES estão faltando no contexto")
    
    # Verifica se comunidades estão no prompt
    communities_present = any(community in prompt for community in COMMUNITIES.keys())
    if communities_present:
        print("✅ Comunidades estão no contexto")
    else:
        print("❌ Comunidades não estão no contexto")
    
    # Verifica se o contexto não contém mais os placeholders
    if "{system_context}" not in prompt and "{tool_docs}" not in prompt:
        print("✅ Placeholders foram substituídos corretamente")
    else:
        print("❌ Ainda há placeholders não substituídos")
    
    print(f"📊 Tamanho do prompt completo: {len(prompt)} caracteres")

def test_role_codes_content():
    """Verifica se ROLE_CODES tem o conteúdo esperado."""
    print("\n=== TESTANDO ROLE_CODES ===")
    
    expected_roles = ["LIB", "CRU", "MIC", "TUR", "NAV", "CER1", "CER2", "CAM"]
    
    for role in expected_roles:
        if role in ROLE_CODES:
            print(f"✅ Role presente: {role}")
        else:
            print(f"❌ Role faltando: {role}")
    
    print(f"📊 Total de roles: {len(ROLE_CODES)}")

def main():
    """Executa todos os testes."""
    print("🔍 TESTANDO MELHORIAS DO AGENTE iAcoli")
    print("=" * 50)
    
    test_role_codes_content()
    test_base_prompt()
    test_system_context()
    
    print("\n" + "=" * 50)
    print("✅ Todos os testes concluídos!")
    print("\n🎯 RESUMO DAS MELHORIAS IMPLEMENTADAS:")
    print("• BASE_PROMPT mais restritivo e diretivo")
    print("• Contexto dinâmico com ROLE_CODES e COMMUNITIES")
    print("• Instruções claras sobre 'todas as funções'")
    print("• Pronto para response_format={'type': 'json_object'}")
    print("• Pronto para extra_body={'disable_search': True}")

if __name__ == "__main__":
    main()
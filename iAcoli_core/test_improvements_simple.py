#!/usr/bin/env python3
"""
Teste simples das melhorias do agente iAcoli.
"""

# Lê os arquivos diretamente para verificar o conteúdo
from pathlib import Path

def test_prompt_builder():
    """Verifica se o prompt_builder.py foi atualizado corretamente."""
    print("🔍 TESTANDO PROMPT_BUILDER.PY")
    print("=" * 50)
    
    pb_file = Path("iacoli_core/agent/prompt_builder.py")
    if not pb_file.exists():
        print("❌ Arquivo não encontrado")
        return False
    
    try:
        content = pb_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = pb_file.read_text(encoding="latin-1")
    
    # Verifica melhorias implementadas
    checks = [
        ("BASE_PROMPT novo formato", "REGRAS CRÍTICAS E INVIOLÁVEIS" in content),
        ("Contexto dinâmico", "{system_context}" in content),
        ("Import ROLE_CODES", "from ..models import ROLE_CODES" in content),
        ("Função build_system_prompt atualizada", "all_roles_str = " in content),
        ("Contexto de comunidades", "COMMUNITIES" in content),
    ]
    
    for check_name, result in checks:
        status = "✅" if result else "❌"
        print(f"{status} {check_name}")
    
    return all(result for _, result in checks)

def test_orchestrator():
    """Verifica se o orchestrator.py foi atualizado corretamente."""
    print("\n🔍 TESTANDO ORCHESTRATOR.PY")
    print("=" * 50)
    
    orch_file = Path("iacoli_core/agent/orchestrator.py")
    if not orch_file.exists():
        print("❌ Arquivo não encontrado")
        return False
    
    content = orch_file.read_text(encoding="utf-8")
    
    # Verifica melhorias implementadas
    checks = [
        ("response_format adicionado", 'response_format={"type": "json_object"}' in content),
        ("disable_search adicionado", '"disable_search": True' in content),
        ("endpoint_map no construtor", "self.endpoint_map = {" in content),
        ("Dispatch refatorado", "key_template = (method, path)" in content),
        ("Comentários em português", "PARÂMETROS CRÍTICOS" in content),
    ]
    
    for check_name, result in checks:
        status = "✅" if result else "❌"
        print(f"{status} {check_name}")
    
    return all(result for _, result in checks)

def test_people_create():
    """Verifica se people_create.md foi atualizado."""
    print("\n🔍 TESTANDO PEOPLE_CREATE.MD")
    print("=" * 50)
    
    pc_file = Path("iacoli_core/agent/tools/people_create.md")
    if not pc_file.exists():
        print("❌ Arquivo não encontrado")
        return False
    
    content = pc_file.read_text(encoding="utf-8")
    
    # Verifica melhorias implementadas
    checks = [
        ("Nota sobre 'todas as funções'", "**Nota Importante:**" in content),
        ("Referência ao contexto", "CONTEXTO ATUAL DO SISTEMA" in content),
        ("Lista completa de códigos", '"LIB", "CRU", "MIC", "TUR", "NAV", "CER1", "CER2", "CAM"' in content),
    ]
    
    for check_name, result in checks:
        status = "✅" if result else "❌"
        print(f"{status} {check_name}")
    
    return all(result for _, result in checks)

def main():
    """Executa todos os testes."""
    print("🎯 VERIFICAÇÃO DAS MELHORIAS DO AGENTE iAcoli")
    print("=" * 60)
    
    results = []
    results.append(test_prompt_builder())
    results.append(test_orchestrator())
    results.append(test_people_create())
    
    print("\n" + "=" * 60)
    if all(results):
        print("🎉 SUCESSO! Todas as melhorias foram implementadas corretamente!")
        print("\n📋 RESUMO DAS CORREÇÕES IMPLEMENTADAS:")
        print("1. ✅ BASE_PROMPT mais restritivo e diretivo")
        print("2. ✅ Contexto dinâmico com ROLE_CODES e COMMUNITIES")
        print("3. ✅ response_format={'type': 'json_object'} na API")
        print("4. ✅ extra_body={'disable_search': True} na API")
        print("5. ✅ Método _dispatch refatorado com dicionário")
        print("6. ✅ Instruções claras sobre 'todas as funções'")
        
        print("\n🚀 PRÓXIMOS PASSOS:")
        print("• Teste o agente com 'cadastrar acólito qualificado com todas as funções'")
        print("• Verifique se ele agora responde apenas em JSON estruturado")
        print("• Confirme que ele usa as ferramentas em vez de dar conselhos gerais")
        
    else:
        print("❌ Algumas verificações falharam. Revise os arquivos.")

if __name__ == "__main__":
    main()
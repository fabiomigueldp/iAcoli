#!/usr/bin/env python3
"""
Test da query com erro de digitação
"""

import sys
sys.path.append(".")

from iacoli_core.webapp.container import ServiceContainer
from iacoli_core.agent import AgentOrchestrator

def test_typo_query():
    container = ServiceContainer()
    orchestrator = AgentOrchestrator(container)
    
    query = "quembsao os acolitos registrados?"
    print(f"🔄 Testando: {query}")
    
    result = orchestrator.interact(query)
    print(f"✅ Resposta: {result['response_text']}")
    print(f"🔧 Ações: {len(result['executed_actions'])}")
    
    if len(result['executed_actions']) == 0:
        print("✅ BYPASS DIRETO!")
    else:
        print("❌ Usou LLM")

if __name__ == "__main__":
    test_typo_query()
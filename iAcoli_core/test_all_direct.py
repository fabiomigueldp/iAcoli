#!/usr/bin/env python3
"""
Test direto do orchestrator para todas as queries
"""

import sys
sys.path.append(".")

from iacoli_core.webapp.container import ServiceContainer
from iacoli_core.agent import AgentOrchestrator

def test_all_queries_direct():
    container = ServiceContainer()
    orchestrator = AgentOrchestrator(container)
    
    queries = [
        "quantos acólitos temos registrados?",
        "liste todos acólitos",
        "quais são os nomes dos acólitos?",
        "todos os acólitos"
    ]
    
    for query in queries:
        print(f"\n🔄 Testando: {query}")
        
        result = orchestrator.interact(query)
        print(f"✅ Resposta: {result['response_text']}")
        print(f"🔧 Ações: {len(result['executed_actions'])}")
        
        if len(result['executed_actions']) == 0:
            print("✅ BYPASS DIRETO!")
        else:
            print("❌ Usou LLM")

if __name__ == "__main__":
    test_all_queries_direct()
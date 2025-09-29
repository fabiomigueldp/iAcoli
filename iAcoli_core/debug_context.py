#!/usr/bin/env python3
"""
Debug do contexto dinâmico
"""

import sys
sys.path.append(".")

from iacoli_core.webapp.container import ServiceContainer
from iacoli_core.agent import AgentOrchestrator

def test_context():
    container = ServiceContainer()
    orchestrator = AgentOrchestrator(container)
    
    context = orchestrator._build_dynamic_context_snapshot()
    print("=== CONTEXTO DINÂMICO ===")
    print(context)
    print("=== FIM ===")

if __name__ == "__main__":
    test_context()
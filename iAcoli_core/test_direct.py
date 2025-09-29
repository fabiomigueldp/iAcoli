#!/usr/bin/env python3
"""
Test direto do orchetrator sem servidor web
"""

import sys
sys.path.append(".")

from iacoli_core.webapp.container import ServiceContainer
from iacoli_core.agent import AgentOrchestrator

def test_direct():
    container = ServiceContainer()
    orchestrator = AgentOrchestrator(container)
    
    result = orchestrator.interact("liste todos acólitos")
    print("=== RESULTADO ===")
    print(f"Response: {result['response_text']}")
    print(f"Actions: {len(result['executed_actions'])}")

if __name__ == "__main__":
    test_direct()
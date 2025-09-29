#!/usr/bin/env python3

import sys
sys.path.append(".")

from iacoli_core.webapp.container import ServiceContainer
from iacoli_core.agent import AgentOrchestrator

def test_names_extraction():
    container = ServiceContainer()
    orchestrator = AgentOrchestrator(container)
    
    context = orchestrator._build_dynamic_context_snapshot()
    
    print("=== CONTEXTO COMPLETO ===")
    lines = context.split('\n')
    for i, line in enumerate(lines):
        print(f"{i:2d}: {line}")
    print("=== FIM ===")
    
    # Simular extração de nomes
    names = []
    in_people_section = False
    
    for i, line in enumerate(lines):
        print(f"Linha {i}: '{line}' - in_people_section: {in_people_section}")
        
        if "pessoas detalhadas" in line.lower():
            in_people_section = True
            print("  -> Entrando na seção de pessoas")
            continue
        elif in_people_section and line.strip().startswith('- '):
            # Linha como "- Emanuelly (id=..., comunidade=..., ativo)"
            name_part = line.strip()[2:].split('(')[0].strip()
            names.append(name_part)
            print(f"  -> Nome extraído: '{name_part}'")
        elif in_people_section and ("proximos eventos" in line.lower() or line.strip().startswith('- Proximos')):
            # Chegou na seção de eventos, parar
            print("  -> Chegou na seção de eventos, parando")
            break
    
    print(f"\n=== NOMES EXTRAÍDOS ===")
    print(f"Nomes: {names}")
    print(f"String final: Os acólitos registrados são: {', '.join(names)}.")

if __name__ == "__main__":
    test_names_extraction()
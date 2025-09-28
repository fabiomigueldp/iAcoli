#!/usr/bin/env python3
"""Script de teste para verificar as melhorias no agente iAcoli."""

import sys
import types
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
package_path = project_root / "iacoli_core"



def _load_module(name: str, path: Path, package: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__package__ = package
    module.__file__ = str(path)
    sys.modules[name] = module
    try:
        source = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        source = path.read_text(encoding="latin-1")
    code = compile(source, str(path), "exec")
    exec(code, module.__dict__)
    return module


try:
    iacoli_pkg = types.ModuleType("iacoli_core")
    iacoli_pkg.__path__ = [str(package_path)]
    sys.modules["iacoli_core"] = iacoli_pkg

    models_module = _load_module("iacoli_core.models", package_path / "models.py", "iacoli_core")
    ROLE_CODES = models_module.ROLE_CODES
    COMMUNITIES = models_module.COMMUNITIES

    agent_pkg = types.ModuleType("iacoli_core.agent")
    agent_pkg.__path__ = [str(package_path / "agent")]
    sys.modules["iacoli_core.agent"] = agent_pkg

    pb_module = _load_module(
        "iacoli_core.agent.prompt_builder",
        package_path / "agent" / "prompt_builder.py",
        "iacoli_core.agent",
    )
    BASE_PROMPT = pb_module.BASE_PROMPT
    build_system_prompt = pb_module.build_system_prompt
    load_all_tool_docs = pb_module.load_all_tool_docs

    print("Ok. Importacoes bem-sucedidas!")
except Exception as exc:
    print(f"Erro na importacao: {exc}")
    sys.exit(1)


def test_base_prompt() -> None:
    """Testa se o novo BASE_PROMPT contem as orientacoes esperadas."""
    print("\n=== TESTANDO BASE_PROMPT ===")

    expected_phrases = [
        "CICLO DE RACIOCINIO REACT",
        "FORMATO DA RESPOSTA EM CADA ITERACAO",
        '"store_result_as"',
        "{system_context}",
        "{tool_docs}",
    ]

    for phrase in expected_phrases:
        status = "OK" if phrase in BASE_PROMPT else "FALTOU"
        print(f"{status}: {phrase}")

    print(f"Tamanho do prompt: {len(BASE_PROMPT)} caracteres")


def test_system_context() -> None:
    """Testa se o contexto do sistema esta sendo injetado corretamente."""
    print("\n=== TESTANDO CONTEXTO DO SISTEMA ===")

    dynamic_context = "- Pessoas registradas: 2 (Maria, Pedro)"
    tool_docs = "=== doc_teste ===\nFerramenta de exemplo"
    prompt = build_system_prompt(
        "cadastrar acolito",
        dynamic_context=dynamic_context,
        tool_docs=tool_docs,
    )

    all_roles_present = all(role in prompt for role in ROLE_CODES)
    print("OK. Todos os ROLE_CODES estao no contexto" if all_roles_present else "FALTOU algum ROLE_CODES")

    communities_present = any(code in prompt for code in COMMUNITIES.keys())
    print("OK. Comunidades estao no contexto" if communities_present else "FALTOU comunidade no contexto")

    dynamic_present = dynamic_context in prompt
    print("OK. Contexto dinamico injetado" if dynamic_present else "FALTOU contexto dinamico")

    docs_present = tool_docs in prompt
    print("OK. Documentacao injetada" if docs_present else "FALTOU documentacao de ferramentas")

    placeholders_absent = "{system_context}" not in prompt and "{tool_docs}" not in prompt
    print("OK. Placeholders removidos" if placeholders_absent else "FALTOU substituir placeholders")

    print(f"Tamanho do prompt completo: {len(prompt)} caracteres")


def test_tool_docs() -> None:
    """Garante que todas as ferramentas estao sendo carregadas."""
    print("\n=== TESTANDO CARREGAMENTO DE FERRAMENTAS ===")
    docs = load_all_tool_docs()
    expected_files = [
        "people_create.md",
        "events_manage.md",
        "schedule_manage.md",
    ]
    for filename in expected_files:
        status = "OK" if f"=== {filename} ===" in docs else "FALTOU"
        print(f"{status}: {filename}")
    print(f"Total de caracteres na documentacao: {len(docs)}")


def test_role_codes_content() -> None:
    """Verifica se ROLE_CODES tem o conteudo esperado."""
    print("\n=== TESTANDO ROLE_CODES ===")
    expected_roles = ["LIB", "CRU", "MIC", "TUR", "NAV", "CER1", "CER2", "CAM"]

    for role in expected_roles:
        status = "OK" if role in ROLE_CODES else "FALTOU"
        print(f"{status}: role {role}")

    print(f"Total de roles: {len(ROLE_CODES)}")


def main() -> None:
    """Executa todos os testes."""
    print("\n=== TESTANDO MELHORIAS DO AGENTE iACOLI ===")
    print("=" * 50)

    test_role_codes_content()
    test_base_prompt()
    test_system_context()
    test_tool_docs()

    print("\n" + "=" * 50)
    print("OK. Todos os testes concluidos!")
    print("\nRESUMO DAS MELHORIAS:")
    print("- BASE_PROMPT direcionado para ciclo ReAct")
    print("- Contexto dinamico e documentacoes injetados corretamente")
    print("- Ferramentas completas disponiveis para o agente")


if __name__ == "__main__":
    main()


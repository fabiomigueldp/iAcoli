#!/usr/bin/env python3
"""Teste simples das melhorias do agente iAcoli."""

from pathlib import Path


def _print_header(title: str) -> None:
    print("\n" + title)
    print("=" * len(title))


def test_prompt_builder() -> bool:
    """Verifica se prompt_builder.py contem as novas instrucoes."""
    _print_header("TESTANDO PROMPT_BUILDER.PY")

    pb_file = Path("iacoli_core/agent/prompt_builder.py")
    if not pb_file.exists():
        print("ERRO: arquivo nao encontrado")
        return False

    content = pb_file.read_text(encoding="utf-8")

    checks = [
        ("Instrucao ReAct presente", "CICLO DE RACIOCINIO REACT" in content),
        ("Uso de store_result_as documentado", '"store_result_as"' in content),
        ("Funcao load_all_tool_docs definida", "def load_all_tool_docs" in content),
        ("build_system_prompt espera dynamic_context", "dynamic_context" in content),
        ("Instrucao de endpoint real", "action.endpoint DEVE usar o formato" in content),
    ]

    all_ok = True
    for description, result in checks:
        status = "OK" if result else "FALHOU"
        print(f"{status}: {description}")
        all_ok &= result
    return all_ok


def test_orchestrator() -> bool:
    """Verifica se orchestrator.py possui o novo ciclo de agente."""
    _print_header("TESTANDO ORCHESTRATOR.PY")

    orch_file = Path("iacoli_core/agent/orchestrator.py")
    if not orch_file.exists():
        print("ERRO: arquivo nao encontrado")
        return False

    content = orch_file.read_text(encoding="utf-8")

    checks = [
        ("response_format json_schema", "response_format=AGENT_RESPONSE_FORMAT" in content),
        ("Funcoes auxiliares de contexto", "_build_dynamic_context_snapshot" in content),
        ("Loop ReAct", "scratchpad" in content and "max_iterations" in content),
        ("Observacoes formatadas", "_format_observation" in content),
        ("Schema constante definida", "AGENT_RESPONSE_FORMAT" in content),
    ]

    all_ok = True
    for description, result in checks:
        status = "OK" if result else "FALHOU"
        print(f"{status}: {description}")
        all_ok &= result
    return all_ok


def test_tool_docs() -> bool:
    """Confere se ao menos uma ferramenta conhecida aparece na documentacao carregada."""
    _print_header("TESTANDO CARREGAMENTO DE DOCUMENTACAO")

    docs_file = Path("iacoli_core/agent/prompt_builder.py")
    if not docs_file.exists():
        print("ERRO: prompt_builder nao encontrado")
        return False

    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location("prompt_builder", docs_file)
    module = module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    docs = module.load_all_tool_docs()
    checks = [
        ("people_create.md presente", "=== people_create.md ===" in docs),
        ("events_manage.md presente", "=== events_manage.md ===" in docs),
        ("schedule_manage.md presente", "=== schedule_manage.md ===" in docs),
    ]

    all_ok = True
    for description, result in checks:
        status = "OK" if result else "FALHOU"
        print(f"{status}: {description}")
        all_ok &= result
    print(f"Total de caracteres nas ferramentas: {len(docs)}")
    return all_ok


def main() -> None:
    """Executa todos os testes simples."""
    print("VERIFICACAO DAS MELHORIAS DO AGENTE iACOLI")
    print("=" * 45)

    results = [
        test_prompt_builder(),
        test_orchestrator(),
        test_tool_docs(),
    ]

    print("\n" + "=" * 45)
    if all(results):
        print("SUCESSO: verificacoes basicas concluídas com sucesso.")
    else:
        print("ATENCAO: algumas verificacoes falharam. Revise as seções acima.")


if __name__ == "__main__":
    main()

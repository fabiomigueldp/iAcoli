#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cli_client.py — cliente interativo para iAcoli Core

Este script oferece um REPL (shell interativo) para executar todos os comandos
do app Typer definido em `iacoli_core.cli`. Ele injeta automaticamente as
opções globais (como --config, --state, --tz, --locale, --format, --seed) em
cada comando digitado, mantém histórico, e pode salvar o estado após cada
comando (auto‑save).

Requisitos: Python 3.11+ e as dependências já usadas pelo projeto (typer/click, pyyaml).
Não há dependências extras.

Uso rápido (interativo):
    python cli_client.py
    python cli_client.py --state state.json --config config.toml --format table

Modo não interativo (pass‑through):
    python cli_client.py evento criar --com MAT --data 2025-10-01 --hora 18:00 -q 4

Comandos meta dentro do REPL (começam com ":"):
    :help [subcomando]     -> mostra ajuda geral (ou de um subcomando)
    :show                  -> mostra parâmetros globais atuais
    :format table|json|csv|yaml
    :autosave on|off       -> liga/desliga auto‑save a cada comando
    :state PATH            -> define caminho do state.json
    :config PATH           -> define caminho do config.toml
    :tz NAME               -> define timezone (ex. America/Sao_Paulo)
    :locale LOCALE         -> define locale (ex. pt-BR)
    :seed N|none           -> define semente determinística (ou 'none' para limpar)
    :run ARQ.txt           -> executa linhas de comandos a partir de um arquivo
    :! <cmd>               -> executa comando do sistema operacional
    :quit | :exit | sair   -> sai do REPL

Dicas:
- Os comandos “normais” são exatamente os mesmos do utilitário `escala` do projeto,
  por exemplo: `evento criar ...`, `escala listar ...`, `acolito adicionar ...` etc.
- O histórico do REPL fica em ~/.escala_client_history (se disponível).
"""

from __future__ import annotations

import argparse
import atexit
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import click  # via Typer
from iacoli_core.cli import app as escala_app, APP_NAME as ESCALA_NAME
from typer.main import get_command
CLICK_CMD = get_command(escala_app)
from iacoli_core.errors import EscalaError, UsageError, ValidationError


HISTORY_PATH = Path.home() / ".escala_client_history"


def _supports_readline() -> bool:
    try:
        import readline  # noqa: F401
        return True
    except Exception:
        return False


def _load_history() -> None:
    if not _supports_readline():
        return
    import readline  # type: ignore
    try:
        readline.read_history_file(str(HISTORY_PATH))
    except FileNotFoundError:
        pass
    atexit.register(lambda: _save_history())


def _save_history() -> None:
    if not _supports_readline():
        return
    import readline  # type: ignore
    try:
        readline.write_history_file(str(HISTORY_PATH))
    except Exception:
        pass


def _split_cmd(line: str) -> List[str]:
    # No Windows tratamos aspas ao estilo cmd; no POSIX usamos padrão.
    posix = os.name != "nt"
    return shlex.split(line, posix=posix)


@dataclass
class Session:
    config_path: Path
    state_path: Path
    tz: Optional[str]
    locale: Optional[str]
    formatter: str
    seed: Optional[int]
    autosave: bool = True

    def build_global_args(self) -> List[str]:
        args: List[str] = []
        if self.config_path:
            args += ["--config", str(self.config_path)]
        if self.state_path:
            args += ["--state", str(self.state_path)]
        if self.tz:
            args += ["--tz", self.tz]
        if self.locale:
            args += ["--locale", self.locale]
        if self.formatter:
            args += ["--format", self.formatter]
        if self.seed is not None:
            args += ["--seed", str(self.seed)]
        return args


class EscalaREPL:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---------------- core execution ----------------

    def _run_escala(self, argv: List[str]) -> int:
        """
        Executa o app Typer subjacente (escala) com argv já tokenizado.
        Retorna o código de saída (0 = OK).
        """
        full_args = self.s.build_global_args() + argv
        try:
            # Typer/Click: standalone_mode=False para levantar exceções em vez de sys.exit.
            return CLICK_CMD.main(args=full_args, prog_name=ESCALA_NAME, standalone_mode=False)  # type: ignore[attr-defined]
        except SystemExit as exc:
            # Gerado por typer.Exit | click.exceptions.Exit
            return int(exc.code or 0)
        except (UsageError, ValidationError, EscalaError) as exc:
            click.secho(str(exc), err=True)
            return getattr(exc, "code", 2) or 2
        except click.ClickException as exc:
            exc.show()
            return 2
        except KeyboardInterrupt:
            click.secho("^C", fg="yellow")
            return 130
        except Exception as exc:  # segurança extra
            click.secho(f"Erro interno: {exc}", err=True, fg="red")
            return 99
        finally:
            if self.s.autosave:
                try:
                    CLICK_CMD.main(
                        args=self.s.build_global_args() + ["arquivo", "salvar"],
                        prog_name=ESCALA_NAME,
                        standalone_mode=False,  # type: ignore[attr-defined]
                    )
                except Exception:
                    # salvar é "best effort"; não quebra a sessão se falhar
                    pass

    # ---------------- meta commands ----------------

    def _meta_help(self, arg: Optional[str]) -> int:
        if arg:
            return self._run_escala(["sistema", "ajuda", arg])
        # ajuda geral: chama app sem subcomando para exibir o help raiz
        return self._run_escala([])

    def _meta_show(self) -> int:
        click.echo(
            "\n".join(
                [
                    "[sessão]",
                    f"  config   = {self.s.config_path}",
                    f"  state    = {self.s.state_path}",
                    f"  tz       = {self.s.tz or '-'}",
                    f"  locale   = {self.s.locale or '-'}",
                    f"  format   = {self.s.formatter}",
                    f"  seed     = {self.s.seed if self.s.seed is not None else '-'}",
                    f"  autosave = {'on' if self.s.autosave else 'off'}",
                ]
            )
        )
        return 0

    def _meta_set(self, what: str, value: Optional[str]) -> int:
        what = what.lower()
        if what == "format":
            if value not in {"table", "json", "csv", "yaml"}:
                click.secho("Formato inválido. Use: table|json|csv|yaml", fg="red")
                return 2
            self.s.formatter = value
        elif what == "autosave":
            if value is None or value.lower() not in {"on", "off"}:
                click.secho("Use ':autosave on' ou ':autosave off'", fg="red")
                return 2
            self.s.autosave = value.lower() == "on"
        elif what == "state":
            if not value:
                click.secho("Informe o caminho do arquivo (ex.: :state state.json)", fg="red")
                return 2
            self.s.state_path = Path(value)
        elif what == "config":
            if not value:
                click.secho("Informe o caminho do arquivo (ex.: :config config.toml)", fg="red")
                return 2
            self.s.config_path = Path(value)
        elif what == "tz":
            self.s.tz = value
        elif what == "locale":
            self.s.locale = value
        elif what == "seed":
            if value is None or value.lower() == "none":
                self.s.seed = None
            else:
                try:
                    self.s.seed = int(value)
                except ValueError:
                    click.secho("Seed inválida (use inteiro ou 'none')", fg="red")
                    return 2
        else:
            click.secho(f"Parâmetro desconhecido: {what}", fg="red")
            return 2
        return 0

    def _meta_runfile(self, path: str) -> int:
        p = Path(path)
        if not p.exists():
            click.secho(f"Arquivo não encontrado: {p}", fg="red")
            return 2
        rc_total = 0
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            click.secho(f"$ {line}", fg="cyan")
            rc = self._run_or_meta(line)
            if rc != 0:
                rc_total = rc
        return rc_total

    # ---------------- dispatch ----------------

    def _run_or_meta(self, line: str) -> int:
        line = line.strip()
        if not line:
            return 0
        # meta: sair
        if line in {":quit", ":exit", "sair", "exit", "quit"}:
            raise EOFError()
        # atalhos de help
        if line.lower() in {"help", "/help", "ajuda", "/ajuda"}:
            return self._meta_help(None)
        # meta: help
        if line.startswith(":help"):
            parts = line.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) == 2 else None
            return self._meta_help(arg)
        # meta: show
        if line == ":show":
            return self._meta_show()
        # meta: format / autosave / state / config / tz / locale / seed
        for key in ("format", "autosave", "state", "config", "tz", "locale", "seed"):
            prefix = f":{key}"
            if line.startswith(prefix):
                parts = line.split(maxsplit=1)
                value = parts[1].strip() if len(parts) == 2 else None
                return self._meta_set(key, value)
        # meta: run file
        if line.startswith(":run "):
            _, path = line.split(" ", 1)
            return self._meta_runfile(path.strip())
        # meta: shell
        if line.startswith(":! "):
            cmd = line[3:].strip()
            try:
                return subprocess.call(cmd, shell=True)
            except KeyboardInterrupt:
                click.secho("^C", fg="yellow")
                return 130
        # comando normal -> passa para o app Typer
        argv = _split_cmd(line)
        return self._run_escala(argv)

    # ---------------- repl loop ----------------

    def loop(self) -> int:
        banner = (
            f"{ESCALA_NAME} interactive shell — digite ':help' para ajuda, 'sair' para sair.\n"
            f"(usando state={self.s.state_path}, config={self.s.config_path}, autosave={'on' if self.s.autosave else 'off'})"
        )
        click.secho(banner, fg="green")
        if _supports_readline():
            _load_history()
        while True:
            try:
                prompt = f"{ESCALA_NAME}> "
                line = input(prompt)
            except EOFError:
                click.echo("")  # newline ao sair com Ctrl+D
                return 0
            except KeyboardInterrupt:
                click.secho("^C", fg="yellow")
                continue
            line = line.strip()
            if not line:
                continue
            try:
                rc = self._run_or_meta(line)
            except EOFError:
                return 0
            if rc not in (0, None):
                # Mostramos código de saída diferente de zero (não interrompe o REPL)
                click.secho(f"(rc={rc})", fg="yellow")

        return 0


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cli_client.py",
        description="REPL para o app 'escala' (iAcoli Core)."
    )
    parser.add_argument("--config", dest="config", default="config.toml", help="Caminho do config TOML (default: config.toml)")
    parser.add_argument("--state", dest="state", default="state.json", help="Arquivo de estado JSON (default: state.json)")
    parser.add_argument("--tz", dest="tz", default=None, help="Fuso horário padrão (opcional)")
    parser.add_argument("--locale", dest="locale", default=None, help="Locale BCP-47 (ex. pt-BR)")
    parser.add_argument("--format", dest="formatter", default="table", choices=["table", "json", "csv", "yaml"], help="Formato de saída padrão")
    parser.add_argument("--seed", dest="seed", type=int, default=None, help="Semente determinística (opcional)")
    parser.add_argument("--no-autosave", dest="no_autosave", action="store_true", help="Desliga auto‑save após cada comando")
    parser.add_argument("cmd", nargs=argparse.REMAINDER, help="(Opcional) Comando para execução direta e sair")
    return parser.parse_args(argv)


def main() -> int:
    ns = parse_args(sys.argv[1:])
    session = Session(
        config_path=Path(ns.config),
        state_path=Path(ns.state),
        tz=ns.tz,
        locale=ns.locale,
        formatter=ns.formatter,
        seed=ns.seed,
        autosave=not ns.no_autosave,
    )
    repl = EscalaREPL(session)

    # Modo pass‑through: se veio um comando após as opções, executa e sai
    if ns.cmd:
        # remover um possível "--" inicial do argparse:
        cmd = ns.cmd
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]
        rc = repl._run_escala(cmd)
        return int(rc or 0)

    # Caso contrário, abre o REPL
    return repl.loop()


if __name__ == "__main__":
    raise SystemExit(main())

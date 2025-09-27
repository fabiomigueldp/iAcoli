from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence
from uuid import UUID

import typer

from .config import Config, DEFAULT_CONFIG_PATH
from .errors import EscalaError, UsageError, ValidationError
from .localization import Localizer
from .models import State, normalize_community, normalize_role
from .output import render_output
from .repository import StateRepository
from .service import CoreService
from .utils import comma_split, combine_date_time, detect_timezone, parse_iso_date, parse_iso_time

APP_NAME = "escala"
DEFAULT_STATE_PATH = Path("state.json")
SUPPORTED_FORMATS = {"table", "json", "csv", "yaml"}

app = typer.Typer(name=APP_NAME, add_completion=False, context_settings={"help_option_names": ["-h", "--help"]})

evento_app = typer.Typer(help="Gerencia eventos.")
serie_app = typer.Typer(help="Gerencia series.")
recorrencia_app = typer.Typer(help="Gerencia recorrencias.")
escala_app = typer.Typer(help="Relatorios e operacoes de escala.")
atribuicao_app = typer.Typer(help="Comandos de atribuicao.")
pool_app = typer.Typer(help="Pools por evento.")
acolito_app = typer.Typer(help="Administracao de acolitos.")
arquivo_app = typer.Typer(help="Persistencia e exportacao.")
config_app = typer.Typer(help="Configuracao do sistema.")
sistema_app = typer.Typer(help="Utilitarios gerais.")

app.add_typer(evento_app, name="evento")
app.add_typer(serie_app, name="serie")
app.add_typer(recorrencia_app, name="recorrencia")
app.add_typer(escala_app, name="escala")
app.add_typer(atribuicao_app, name="atribuicao")
app.add_typer(pool_app, name="pool")
app.add_typer(acolito_app, name="acolito")
app.add_typer(arquivo_app, name="arquivo")
app.add_typer(config_app, name="config")
app.add_typer(sistema_app, name="sistema")

acolito_qual_app = typer.Typer(help="Qualificacoes dos acolitos.")
acolito_app.add_typer(acolito_qual_app, name="qual")

arquivo_exportar_app = typer.Typer(help="Exportacoes de dados.")
arquivo_app.add_typer(arquivo_exportar_app, name="exportar")


@dataclass
class AppContext:
    config: Config
    config_path: Path
    state_path: Path
    repo: StateRepository
    service: CoreService
    formatter: str
    locale: str
    seed: int | None
    localizer: Localizer


def _ensure_format(value: str) -> str:
    fmt = value.lower()
    if fmt not in SUPPORTED_FORMATS:
        raise UsageError(f"Formato nao suportado: {value}")
    return fmt


def parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise UsageError(f"{label} invalido: {value}") from exc


def parse_roles_option(raw: Optional[str]) -> Optional[list[str]]:
    if not raw:
        return None
    return [normalize_role(token) for token in comma_split(raw)]


def parse_com_option(raw: Optional[str]) -> Optional[list[str]]:
    if not raw:
        return None
    return [normalize_community(token) for token in comma_split(raw)]


def get_ctx(ctx: typer.Context) -> AppContext:
    if not isinstance(ctx.obj, AppContext):
        raise RuntimeError("Contexto nao inicializado")
    return ctx.obj


def print_rows(
    ctx: AppContext,
    rows: Sequence[dict],
    columns: Sequence[str],
    *,
    fmt: Optional[str] = None,
    name_width: int | None = None,
) -> None:
    formatter = _ensure_format(fmt or ctx.formatter)
    widths: dict[str, int] = {}
    if name_width:
        widths["acolito"] = name_width
        widths["nome"] = name_width
    text = render_output(rows, columns, formatter, width_overrides=widths)
    typer.echo(text)


def parse_time_window(raw: Optional[str]) -> tuple[str, str]:
    if not raw:
        return ("00:00", "23:59")
    if ".." not in raw:
        raise UsageError("Use HH:MM..HH:MM em --hora.")
    start_str, end_str = raw.split("..", 1)
    return start_str, end_str


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config_path: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Caminho do config TOML."),
    state_path: Path = typer.Option(DEFAULT_STATE_PATH, "--state", help="Arquivo de estado JSON."),
    tz: Optional[str] = typer.Option(None, "--tz", help="Fuso horario padrao."),
    locale: Optional[str] = typer.Option(None, "--locale", help="Locale BCP-47."),
    formatter: str = typer.Option("table", "--format", help="table|json|csv|yaml"),
    seed: Optional[int] = typer.Option(None, "--seed", help="Semente deterministica."),
) -> None:
    overrides: dict[str, Any] = {}
    if tz:
        overrides["general.timezone"] = tz
    if locale:
        overrides["general.default_locale"] = locale
    config = Config.load(path=config_path, env=os.environ, overrides=overrides)
    repo = StateRepository(state_path)
    service = CoreService(repo, config)
    ctx.obj = AppContext(
        config=config,
        config_path=config_path,
        state_path=state_path,
        repo=repo,
        service=service,
        formatter=_ensure_format(formatter),
        locale=locale or config.general.default_locale,
        seed=seed,
        localizer=Localizer(locale or config.general.default_locale),
    )
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@evento_app.command("criar")
def evento_criar(
    ctx: typer.Context,
    com: str = typer.Option(..., "--com"),
    data: str = typer.Option(..., "--data"),
    hora: str = typer.Option(..., "--hora"),
    quantidade: int = typer.Option(..., "-q", "--quantidade", min=1),
    kind: str = typer.Option("REG", "--kind"),
    aids: Optional[str] = typer.Option(None, "--aids"),
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    pool_ids = [parse_uuid(token, "AID") for token in comma_split(aids or "")] if aids else []
    event = app_ctx.service.create_event(
        community=normalize_community(com),
        date_str=data,
        time_str=hora,
        tz_name=app_ctx.config.general.timezone,
        quantity=quantidade,
        kind=kind.upper(),
        pool=pool_ids,
    )
    rows = [
        {
            "id": str(event.id),
            "key": event.key(),
            "community": event.community,
            "data": event.dtstart.date().isoformat(),
            "hora": event.dtstart.strftime("%H:%M"),
            "qty": event.quantity,
            "kind": event.kind,
        }
    ]
    print_rows(app_ctx, rows, ["id", "key", "community", "data", "hora", "qty", "kind"], fmt=format)


@evento_app.command("editar")
def evento_editar(
    ctx: typer.Context,
    identifier: str = typer.Argument(..., help="ID ou EventKey"),
    com: Optional[str] = typer.Option(None, "--com"),
    data: Optional[str] = typer.Option(None, "--data"),
    hora: Optional[str] = typer.Option(None, "--hora"),
    quantidade: Optional[int] = typer.Option(None, "-q", "--quantidade"),
    kind: Optional[str] = typer.Option(None, "--kind"),
    aids: Optional[str] = typer.Option(None, "--aids"),
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    pool_ids = [parse_uuid(token, "AID") for token in comma_split(aids or "")] if aids else None
    updated = app_ctx.service.update_event(
        identifier,
        community=normalize_community(com) if com else None,
        date_str=data,
        time_str=hora,
        quantity=quantidade,
        kind=kind.upper() if kind else None,
        pool=pool_ids,
    )
    rows = [
        {
            "id": str(updated.id),
            "key": updated.key(),
            "community": updated.community,
            "data": updated.dtstart.date().isoformat(),
            "hora": updated.dtstart.strftime("%H:%M"),
            "qty": updated.quantity,
            "kind": updated.kind,
        }
    ]
    print_rows(app_ctx, rows, ["id", "key", "community", "data", "hora", "qty", "kind"], fmt=format)


@evento_app.command("remover")
def evento_remover(
    ctx: typer.Context,
    identifier: Optional[str] = typer.Argument(None, help="ID ou EventKey"),
    dia: Optional[str] = typer.Option(None, "--dia", help="Remove todos os eventos na data informada"),
) -> None:
    app_ctx = get_ctx(ctx)
    if dia:
        removed = 0
        for event in list(app_ctx.service.list_events()):
            if event.dtstart.date().isoformat() == dia:
                app_ctx.service.remove_event(str(event.id))
                removed += 1
        typer.echo(f"ðŸ—‘ï¸ {removed} eventos removidos em {dia}.")
        return
    if not identifier:
        raise UsageError("Informe ID/EventKey ou --dia.")
    app_ctx.service.remove_event(identifier)
    typer.echo("ðŸ—‘ï¸ Evento removido.")


@evento_app.command("mostrar")
def evento_mostrar(
    ctx: typer.Context,
    identifier: str = typer.Argument(..., help="ID ou EventKey"),
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    event = app_ctx.service.get_event(identifier)
    assignments = app_ctx.service.state.assignments.get(event.id, {})
    rows = [
        {
            "id": str(event.id),
            "key": event.key(),
            "community": event.community,
            "data": event.dtstart.date().isoformat(),
            "hora": event.dtstart.strftime("%H:%M"),
            "qty": event.quantity,
            "kind": event.kind,
            "atrib": ", ".join(
                f"{role}:{app_ctx.service.state.people.get(pid).name if app_ctx.service.state.people.get(pid) else pid}"
                for role, pid in sorted(assignments.items())
            ),
        }
    ]
    print_rows(app_ctx, rows, ["id", "key", "community", "data", "hora", "qty", "kind", "atrib"], fmt=format)

@serie_app.command("criar")
def serie_criar(
    ctx: typer.Context,
    base: str = typer.Option(..., "--base", help="ID do evento base"),
    dias: int = typer.Option(..., "--dias", min=1),
    kind: str = typer.Option("REG", "--kind"),
    aids: Optional[str] = typer.Option(None, "--aids"),
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    series = app_ctx.service.create_series(
        base_event_id=parse_uuid(base, "event_id"),
        days=dias,
        kind=kind.upper(),
        pool=[parse_uuid(token, "AID") for token in comma_split(aids or "")] if aids else None,
    )
    rows = [
        {
            "id": str(series.id),
            "base": str(series.base_event_id),
            "dias": series.days,
            "kind": series.kind,
            "pool": len(series.pool or []),
        }
    ]
    print_rows(app_ctx, rows, ["id", "base", "dias", "kind", "pool"], fmt=format)


@serie_app.command("rebasear")
def serie_rebasear(
    ctx: typer.Context,
    series_id: str = typer.Option(..., "--id"),
    novo_base: str = typer.Option(..., "--novo-base"),
    aids: Optional[str] = typer.Option(None, "--aids"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.rebase_series(
        series_id=parse_uuid(series_id, "series_id"),
        new_base_event_id=parse_uuid(novo_base, "event_id"),
        pool=[parse_uuid(token, "AID") for token in comma_split(aids or "")] if aids else None,
    )
    typer.echo("ðŸ” Serie rebaseada.")


@serie_app.command("remover")
def serie_remover(
    ctx: typer.Context,
    series_id: str = typer.Option(..., "--id"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.remove_series(parse_uuid(series_id, "series_id"))
    typer.echo("ðŸ—‘ï¸ Serie removida.")


@recorrencia_app.command("criar")
def recorrencia_criar(
    ctx: typer.Context,
    com: str = typer.Option(..., "--com"),
    data: str = typer.Option(..., "--data"),
    hora: str = typer.Option(..., "--hora"),
    quantidade: int = typer.Option(..., "-q", "--quantidade", min=1),
    rrule: str = typer.Option(..., "--rrule"),
    aids: Optional[str] = typer.Option(None, "--aids"),
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    tz = detect_timezone(app_ctx.config.general.timezone)
    dtstart = combine_date_time(parse_iso_date(data), parse_iso_time(hora), tz)
    rec = app_ctx.service.create_recurrence(
        community=normalize_community(com),
        dtstart_base=dtstart,
        rrule=rrule,
        quantity=quantidade,
        pool=[parse_uuid(token, "AID") for token in comma_split(aids or "")] if aids else None,
    )
    rows = [
        {
            "id": str(rec.id),
            "com": rec.community,
            "dtstart": rec.dtstart_base.isoformat(),
            "rrule": rec.rrule,
            "qty": rec.quantity,
        }
    ]
    print_rows(app_ctx, rows, ["id", "com", "dtstart", "rrule", "qty"], fmt=format)


@recorrencia_app.command("editar")
def recorrencia_editar(
    ctx: typer.Context,
    rec_id: str = typer.Option(..., "--id"),
    rrule: Optional[str] = typer.Option(None, "--rrule"),
    quantidade: Optional[int] = typer.Option(None, "-q", "--quantidade"),
    aids: Optional[str] = typer.Option(None, "--aids"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.update_recurrence(
        parse_uuid(rec_id, "rec_id"),
        rrule=rrule,
        quantity=quantidade,
        pool=[parse_uuid(token, "AID") for token in comma_split(aids or "")] if aids else None,
    )
    typer.echo("âœï¸ Recorrencia atualizada.")


@recorrencia_app.command("remover")
def recorrencia_remover(
    ctx: typer.Context,
    rec_id: str = typer.Option(..., "--id"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.remove_recurrence(parse_uuid(rec_id, "rec_id"))
    typer.echo("ðŸ—‘ï¸ Recorrencia removida.")

@escala_app.command("listar")
def escala_listar(
    ctx: typer.Context,
    periodo: Optional[str] = typer.Option(None, "--periodo"),
    de: Optional[str] = typer.Option(None, "--de"),
    ate: Optional[str] = typer.Option(None, "--ate"),
    com: Optional[str] = typer.Option(None, "--com"),
    roles: Optional[str] = typer.Option(None, "--roles"),
    format: Optional[str] = typer.Option(None, "--format"),
    name_width: int = typer.Option(0, "--name-width"),
) -> None:
    app_ctx = get_ctx(ctx)
    rows = app_ctx.service.list_schedule(
        periodo=periodo,
        de=de,
        ate=ate,
        communities=parse_com_option(com),
        roles=parse_roles_option(roles),
    )
    width = name_width if name_width > 0 else app_ctx.config.general.name_width
    print_rows(app_ctx, rows, ["event", "community", "data", "hora", "role", "acolito"], fmt=format, name_width=width)


@escala_app.command("recalcular")
def escala_recalcular(
    ctx: typer.Context,
    periodo: Optional[str] = typer.Option(None, "--periodo"),
    de: Optional[str] = typer.Option(None, "--de"),
    ate: Optional[str] = typer.Option(None, "--ate"),
    seed: Optional[int] = typer.Option(None, "--seed"),
) -> None:
    app_ctx = get_ctx(ctx)
    final_seed = seed if seed is not None else app_ctx.seed
    app_ctx.service.recalculate(periodo=periodo, de=de, ate=ate, seed=final_seed)
    typer.echo(app_ctx.localizer.text("assignment.done"))


@escala_app.command("livres")
def escala_livres(
    ctx: typer.Context,
    periodo: Optional[str] = typer.Option(None, "--periodo"),
    de: Optional[str] = typer.Option(None, "--de"),
    ate: Optional[str] = typer.Option(None, "--ate"),
    com: Optional[str] = typer.Option(None, "--com"),
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    rows = app_ctx.service.list_free_slots(periodo=periodo, de=de, ate=ate, communities=parse_com_option(com))
    print_rows(app_ctx, rows, ["event", "community", "data", "hora", "role"], fmt=format)


@escala_app.command("sugerir")
def escala_sugerir(
    ctx: typer.Context,
    event: str = typer.Option(..., "--event"),
    role: str = typer.Option(..., "--role"),
    top: int = typer.Option(5, "--top", min=1),
    format: Optional[str] = typer.Option(None, "--format"),
    seed: Optional[int] = typer.Option(None, "--seed"),
) -> None:
    app_ctx = get_ctx(ctx)
    rows = app_ctx.service.suggest_candidates(
        event,
        normalize_role(role),
        top=top,
        seed=seed if seed is not None else app_ctx.seed,
    )
    print_rows(app_ctx, rows, ["person_id", "nome", "com", "score", "overflow"], fmt=format, name_width=app_ctx.config.general.name_width)


@escala_app.command("checar")
def escala_checar(
    ctx: typer.Context,
    periodo: Optional[str] = typer.Option(None, "--periodo"),
    de: Optional[str] = typer.Option(None, "--de"),
    ate: Optional[str] = typer.Option(None, "--ate"),
    com: Optional[str] = typer.Option(None, "--com"),
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    rows = app_ctx.service.check_schedule(periodo=periodo, de=de, ate=ate, communities=parse_com_option(com))
    print_rows(app_ctx, rows, ["severity", "event", "issue"], fmt=format)


@escala_app.command("stats")
def escala_stats(
    ctx: typer.Context,
    periodo: Optional[str] = typer.Option(None, "--periodo"),
    de: Optional[str] = typer.Option(None, "--de"),
    ate: Optional[str] = typer.Option(None, "--ate"),
    com: Optional[str] = typer.Option(None, "--com"),
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    rows = app_ctx.service.stats(periodo=periodo, de=de, ate=ate, communities=parse_com_option(com))
    print_rows(app_ctx, rows, ["person_id", "nome", "com", "total", "roles"], fmt=format, name_width=app_ctx.config.general.name_width)


@atribuicao_app.command("aplicar")
def atribuicao_aplicar(
    ctx: typer.Context,
    event: str = typer.Option(..., "--event"),
    role: str = typer.Option(..., "--role"),
    aid: str = typer.Option(..., "--aid"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.apply_assignment(event, normalize_role(role), parse_uuid(aid, "AID"))
    typer.echo("âœ… Atribuicao aplicada.")


@atribuicao_app.command("limpar")
def atribuicao_limpar(
    ctx: typer.Context,
    event: str = typer.Option(..., "--event"),
    role: str = typer.Option(..., "--role"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.clear_assignment(event, normalize_role(role))
    typer.echo("ðŸ§¹ Atribuicao removida.")


@atribuicao_app.command("trocar")
def atribuicao_trocar(
    ctx: typer.Context,
    event_a: str = typer.Option(..., "--event-a"),
    role_a: str = typer.Option(..., "--role-a"),
    event_b: str = typer.Option(..., "--event-b"),
    role_b: str = typer.Option(..., "--role-b"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.swap_assignments(event_a, normalize_role(role_a), event_b, normalize_role(role_b))
    typer.echo("ðŸ” Troca realizada.")


@atribuicao_app.command("resetar")
def atribuicao_resetar(
    ctx: typer.Context,
    periodo: Optional[str] = typer.Option(None, "--periodo"),
    de: Optional[str] = typer.Option(None, "--de"),
    ate: Optional[str] = typer.Option(None, "--ate"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.reset_assignments(periodo=periodo, de=de, ate=ate)
    typer.echo("ðŸ§¹ Atribuicoes removidas.")


@pool_app.command("set")
def pool_set(
    ctx: typer.Context,
    event: str = typer.Option(..., "--event"),
    aids: str = typer.Option(..., "--aids"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.set_pool(event, [parse_uuid(token, "AID") for token in comma_split(aids)])
    typer.echo("âœ… Pool atualizado.")


@pool_app.command("clear")
def pool_clear(
    ctx: typer.Context,
    event: str = typer.Option(..., "--event"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.clear_pool(event)
    typer.echo("ðŸ§¹ Pool removido.")


@pool_app.command("show")
def pool_show(
    ctx: typer.Context,
    event: str = typer.Option(..., "--event"),
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    info = app_ctx.service.pool_info(event)
    rows = info["members"] or [{"person_id": "-", "nome": "(vazio)", "com": "-"}]
    print_rows(app_ctx, rows, ["person_id", "nome", "com"], fmt=format, name_width=app_ctx.config.general.name_width)

@acolito_app.command("listar")
def acolito_listar(
    ctx: typer.Context,
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    rows = [
        {
            "id": str(person.id),
            "nome": person.name,
            "com": person.community,
            "roles": ",".join(sorted(person.roles)) or "-",
            "ativo": "sim" if person.active else "nao",
        }
        for person in app_ctx.service.list_people()
    ]
    print_rows(app_ctx, rows, ["id", "nome", "com", "roles", "ativo"], fmt=format, name_width=app_ctx.config.general.name_width)


@acolito_app.command("mostrar")
def acolito_mostrar(
    ctx: typer.Context,
    aid: str = typer.Option(..., "--id"),
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    detail = app_ctx.service.person_detail(parse_uuid(aid, "AID"))
    print_rows(app_ctx, [detail], ["id", "name", "community", "roles", "morning", "active", "blocks"], fmt=format, name_width=app_ctx.config.general.name_width)


@acolito_app.command("adicionar")
def acolito_adicionar(
    ctx: typer.Context,
    nome: str = typer.Option(..., "--name"),
    com: str = typer.Option(..., "--com"),
    roles: Optional[str] = typer.Option(None, "--roles"),
    manha: bool = typer.Option(False, "--manha"),
    ativo: bool = typer.Option(True, "--ativo"),
    locale: Optional[str] = typer.Option(None, "--locale"),
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    person = app_ctx.service.add_person(
        name=nome,
        community=normalize_community(com),
        roles=parse_roles_option(roles) or [],
        morning=manha,
        active=ativo,
        locale=locale,
    )
    rows = [{"id": str(person.id), "nome": person.name, "com": person.community, "roles": ",".join(sorted(person.roles)) or "-"}]
    print_rows(app_ctx, rows, ["id", "nome", "com", "roles"], fmt=format, name_width=app_ctx.config.general.name_width)


@acolito_app.command("set")
def acolito_set(
    ctx: typer.Context,
    aid: str = typer.Option(..., "--id"),
    nome: Optional[str] = typer.Option(None, "--name"),
    com: Optional[str] = typer.Option(None, "--com"),
    roles: Optional[str] = typer.Option(None, "--roles"),
    manha: Optional[bool] = typer.Option(None, "--manha"),
    ativo: Optional[bool] = typer.Option(None, "--ativo"),
    locale: Optional[str] = typer.Option(None, "--locale"),
) -> None:
    app_ctx = get_ctx(ctx)
    person = app_ctx.service.update_person(
        parse_uuid(aid, "AID"),
        name=nome,
        community=normalize_community(com) if com else None,
        roles=parse_roles_option(roles),
        morning=manha,
        active=ativo,
        locale=locale,
    )
    typer.echo(f"âœï¸ Atualizado: {person.name}.")


@acolito_app.command("remover")
def acolito_remover(
    ctx: typer.Context,
    aid: str = typer.Option(..., "--id"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.remove_person(parse_uuid(aid, "AID"))
    typer.echo("ðŸ—‘ï¸ Acolito removido.")


@acolito_app.command("bloquear")
def acolito_bloquear(
    ctx: typer.Context,
    aid: str = typer.Option(..., "--id"),
    de: str = typer.Option(..., "--de"),
    ate: str = typer.Option(..., "--ate"),
    hora: Optional[str] = typer.Option(None, "--hora"),
    nota: Optional[str] = typer.Option(None, "--nota"),
) -> None:
    app_ctx = get_ctx(ctx)
    tz = detect_timezone(app_ctx.config.general.timezone)
    start_h, end_h = parse_time_window(hora)
    start_dt = combine_date_time(parse_iso_date(de), parse_iso_time(start_h), tz)
    end_dt = combine_date_time(parse_iso_date(ate), parse_iso_time(end_h), tz)
    app_ctx.service.add_block(parse_uuid(aid, "AID"), start=start_dt, end=end_dt, note=nota)
    typer.echo("â›” Bloqueio registrado.")


@acolito_app.command("desbloquear")
def acolito_desbloquear(
    ctx: typer.Context,
    aid: str = typer.Option(..., "--id"),
    indice: Optional[int] = typer.Option(None, "--indice"),
    remover_todos: bool = typer.Option(False, "--all", help="Remove todos os bloqueios"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.remove_block(parse_uuid(aid, "AID"), index=indice, remove_all=remover_todos)
    typer.echo("âœ… Bloqueio removido.")


@acolito_qual_app.command("listar")
def acolito_qual_listar(
    ctx: typer.Context,
    aid: str = typer.Option(..., "--id"),
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    person = app_ctx.service.get_person(parse_uuid(aid, "AID"))
    rows = [{"role": role} for role in sorted(person.roles)] or [{"role": "-"}]
    print_rows(app_ctx, rows, ["role"], fmt=format)


@acolito_qual_app.command("set")
def acolito_qual_set(
    ctx: typer.Context,
    aid: str = typer.Option(..., "--id"),
    roles: str = typer.Option(..., "--roles"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.set_roles(parse_uuid(aid, "AID"), parse_roles_option(roles) or [])
    typer.echo("âœ… Funcoes definidas.")


@acolito_qual_app.command("add")
def acolito_qual_add(
    ctx: typer.Context,
    aid: str = typer.Option(..., "--id"),
    roles: str = typer.Option(..., "--roles"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.add_roles(parse_uuid(aid, "AID"), parse_roles_option(roles) or [])
    typer.echo("âœ… Funcoes adicionadas.")


@acolito_qual_app.command("del")
def acolito_qual_del(
    ctx: typer.Context,
    aid: str = typer.Option(..., "--id"),
    roles: str = typer.Option(..., "--roles"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.remove_roles(parse_uuid(aid, "AID"), parse_roles_option(roles) or [])
    typer.echo("ðŸ—‘ï¸ Funcoes removidas.")


@acolito_qual_app.command("clear")
def acolito_qual_clear(
    ctx: typer.Context,
    aid: str = typer.Option(..., "--id"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.clear_roles(parse_uuid(aid, "AID"))
    typer.echo("ðŸ§¹ Funcoes limpas.")

@arquivo_app.command("salvar")
def arquivo_salvar(
    ctx: typer.Context,
    path: Optional[Path] = typer.Option(None, "--path"),
) -> None:
    app_ctx = get_ctx(ctx)
    target = app_ctx.service.save_state(str(path) if path else None)
    typer.echo(app_ctx.localizer.text("state.saved", path=target))


@arquivo_app.command("carregar")
def arquivo_carregar(
    ctx: typer.Context,
    path: Path = typer.Option(..., "--path"),
) -> None:
    app_ctx = get_ctx(ctx)
    target = app_ctx.service.load_state(str(path))
    typer.echo(app_ctx.localizer.text("state.loaded", path=target))


@arquivo_exportar_app.command("csv")
def arquivo_exportar_csv(
    ctx: typer.Context,
    path: Path = typer.Option(..., "--path"),
    periodo: Optional[str] = typer.Option(None, "--periodo"),
    de: Optional[str] = typer.Option(None, "--de"),
    ate: Optional[str] = typer.Option(None, "--ate"),
    com: Optional[str] = typer.Option(None, "--com"),
    roles: Optional[str] = typer.Option(None, "--roles"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.export_csv(
        path=path,
        periodo=periodo,
        de=de,
        ate=ate,
        communities=parse_com_option(com),
        roles=parse_roles_option(roles),
    )
    typer.echo(f"ðŸ’¾ CSV salvo em {path}.")


@arquivo_exportar_app.command("ics")
def arquivo_exportar_ics(
    ctx: typer.Context,
    path: Path = typer.Option(..., "--path"),
    periodo: Optional[str] = typer.Option(None, "--periodo"),
    de: Optional[str] = typer.Option(None, "--de"),
    ate: Optional[str] = typer.Option(None, "--ate"),
    com: Optional[str] = typer.Option(None, "--com"),
    tz: Optional[str] = typer.Option(None, "--tz"),
) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.service.export_ics(
        path=path,
        periodo=periodo,
        de=de,
        ate=ate,
        communities=parse_com_option(com),
        tz_name=tz,
    )
    typer.echo(f"ðŸ’¾ ICS salvo em {path}.")


@config_app.command("mostrar")
def config_mostrar(
    ctx: typer.Context,
    format: Optional[str] = typer.Option(None, "--format"),
) -> None:
    app_ctx = get_ctx(ctx)
    cfg = app_ctx.config
    rows = [
        {"secao": "general", "chave": "timezone", "valor": cfg.general.timezone},
        {"secao": "general", "chave": "default_view_days", "valor": cfg.general.default_view_days},
        {"secao": "general", "chave": "name_width", "valor": cfg.general.name_width},
        {"secao": "general", "chave": "overlap_minutes", "valor": cfg.general.overlap_minutes},
        {"secao": "general", "chave": "default_locale", "valor": cfg.general.default_locale},
        {"secao": "fairness", "chave": "fair_window_days", "valor": cfg.fairness.fair_window_days},
        {"secao": "fairness", "chave": "role_rot_window_days", "valor": cfg.fairness.role_rot_window_days},
        {"secao": "fairness", "chave": "workload_tolerance", "valor": cfg.fairness.workload_tolerance},
        {"secao": "weights", "chave": "load_balance", "valor": cfg.weights.load_balance},
        {"secao": "weights", "chave": "recency", "valor": cfg.weights.recency},
        {"secao": "weights", "chave": "role_rotation", "valor": cfg.weights.role_rotation},
        {"secao": "weights", "chave": "morning_pref", "valor": cfg.weights.morning_pref},
        {"secao": "weights", "chave": "solene_bonus", "valor": cfg.weights.solene_bonus},
    ]
    print_rows(app_ctx, rows, ["secao", "chave", "valor"], fmt=format)


@config_app.command("setar")
def config_setar(
    ctx: typer.Context,
    timezone: Optional[str] = typer.Option(None, "--timezone"),
    view_days: Optional[int] = typer.Option(None, "--view-days"),
    name_width: Optional[int] = typer.Option(None, "--name-width"),
    overlap: Optional[int] = typer.Option(None, "--overlap"),
    fair_days: Optional[int] = typer.Option(None, "--fair-days"),
    role_rot_days: Optional[int] = typer.Option(None, "--role-rot-days"),
    workload_tolerance: Optional[int] = typer.Option(None, "--workload-tolerance"),
) -> None:
    app_ctx = get_ctx(ctx)
    cfg = app_ctx.config
    if timezone:
        cfg.general.timezone = timezone
    if view_days is not None:
        cfg.general.default_view_days = view_days
    if name_width is not None:
        cfg.general.name_width = name_width
    if overlap is not None:
        cfg.general.overlap_minutes = overlap
    if fair_days is not None:
        cfg.fairness.fair_window_days = fair_days
    if role_rot_days is not None:
        cfg.fairness.role_rot_window_days = role_rot_days
    if workload_tolerance is not None:
        cfg.fairness.workload_tolerance = workload_tolerance
    cfg.validate()
    app_ctx.config_path.write_text(cfg.to_toml(), encoding="utf-8")
    app_ctx.service = CoreService(app_ctx.repo, cfg)
    typer.echo("âœ… Configuracao atualizada.")


@sistema_app.command("agora")
def sistema_agora(ctx: typer.Context) -> None:
    app_ctx = get_ctx(ctx)
    tz = detect_timezone(app_ctx.config.general.timezone)
    typer.echo(datetime.now(tz).isoformat())


@sistema_app.command("limpar")
def sistema_limpar(ctx: typer.Context) -> None:
    app_ctx = get_ctx(ctx)
    app_ctx.repo.push_history("system.clear")
    app_ctx.repo.state = State()
    typer.echo("ðŸ§¹ Estado atual limpo (nao salvo).")


@sistema_app.command("undo")
def sistema_undo(ctx: typer.Context) -> None:
    app_ctx = get_ctx(ctx)
    try:
        snapshot = app_ctx.repo.undo()
    except ValidationError:
        typer.echo(app_ctx.localizer.text("undo.empty"))
        return
    typer.echo(app_ctx.localizer.text("undo.applied", label=snapshot.label))


@sistema_app.command("sair")
def sistema_sair() -> None:
    raise typer.Exit()


@sistema_app.command("ajuda")
def sistema_ajuda(ctx: typer.Context, comando: Optional[str] = typer.Argument(None)) -> None:
    if not comando:
        typer.echo(ctx.parent.get_help())
        return
    command = ctx.parent.command
    sub = command.get_command(ctx.parent, comando)
    if not sub:
        raise UsageError(f"Comando desconhecido: {comando}")
    typer.echo(sub.get_help(ctx.parent))


# entrada principal
def main_entry() -> None:
    try:
        app()
    except UsageError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(2)
    except ValidationError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(3)
    except EscalaError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(exc.code)
    except Exception as exc:  # pragma: no cover
        typer.secho(f"Erro interno: {exc}", err=True)
        raise typer.Exit(6)


main = main_entry

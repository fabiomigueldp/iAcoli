from __future__ import annotations

import csv
import io
import json
from typing import Any, Mapping, Sequence

import yaml

ELLIPSIS = "..."


def truncate(value: str, width: int) -> str:
    if width <= 0:
        return value
    if len(value) <= width:
        return value
    if width <= len(ELLIPSIS):
        return value[:width]
    return value[: width - len(ELLIPSIS)] + ELLIPSIS


def format_cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def render_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str], widths: Mapping[str, int] | None = None) -> str:
    widths = widths or {}
    col_widths: list[int] = []
    for column in columns:
        base = max(len(column), *(len(format_cell(row.get(column))) for row in rows)) if rows else len(column)
        target = widths.get(column, 0)
        col_widths.append(max(base, target))
    header = " | ".join(column.ljust(col_widths[idx]) for idx, column in enumerate(columns))
    divider = "-+-".join("-" * col_widths[idx] for idx in range(len(columns)))
    body_lines = []
    for row in rows:
        cells = []
        for idx, column in enumerate(columns):
            cell = format_cell(row.get(column))
            width = widths.get(column)
            if width:
                cell = truncate(cell, width)
            cells.append(cell.ljust(col_widths[idx]))
        body_lines.append(" | ".join(cells))
    if not body_lines:
        body_lines.append("(sem registros)")
    return "\n".join([header, divider, *body_lines])


def render_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def render_yaml(data: Any) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def render_csv(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns))
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()


def render_output(rows: Sequence[Mapping[str, Any]], columns: Sequence[str], fmt: str, *, width_overrides: Mapping[str, int] | None = None) -> str:
    fmt = fmt.lower()
    if fmt == "table":
        return render_table(rows, columns, widths=width_overrides)
    data = [dict(row) for row in rows]
    if fmt == "json":
        return render_json(data)
    if fmt == "yaml":
        return render_yaml(data)
    if fmt == "csv":
        return render_csv(data, columns)
    raise ValueError(f"Formato nao suportado: {fmt}")

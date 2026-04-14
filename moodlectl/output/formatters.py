from __future__ import annotations

import json

from rich.console import Console
from rich.table import Table

console = Console()


def print_table(data: list[dict], columns: list[str], fmt: str = "table") -> None:
    if not data:
        console.print("[yellow]No data.[/yellow]")
        return

    if fmt == "json":
        rows = [{k: row.get(k, "") for k in columns} for row in data]
        console.print_json(json.dumps(rows, default=str))
        return

    if fmt == "csv":
        print(",".join(columns))
        for row in data:
            print(",".join(str(row.get(k, "")) for k in columns))
        return

    table = Table(show_header=True, header_style="bold cyan")
    for col in columns:
        table.add_column(col.replace("_", " ").title())

    for row in data:
        table.add_row(*[str(row.get(k, "")) for k in columns])

    console.print(table)

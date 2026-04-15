from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from rich.console import Console
from rich.table import Table

from moodlectl.types import OutputFmt

# legacy_windows=False forces Rich to use ANSI escape codes rather than the
# Win32 console API, which only supports cp1252 and breaks on Arabic/Unicode.
console = Console(legacy_windows=False)


def print_table(data: Sequence[Mapping[str, object]], columns: list[str], fmt: OutputFmt = "table") -> None:
    if not data:
        console.print("[yellow]No data.[/yellow]")
        return

    if fmt == "json":
        rows = [{k: row.get(k, "") for k in columns} for row in data]
        console.print_json(json.dumps(rows, default=str))
        return

    if fmt == "csv":
        import csv
        import io
        import sys
        # Write UTF-8 bytes directly so Arabic/Unicode columns survive on Windows
        buf = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8-sig", newline="")
        writer = csv.writer(buf)
        writer.writerow(columns)
        for row in data:
            writer.writerow([str(row.get(k, "")) for k in columns])
        buf.flush()
        buf.detach()  # don't close underlying stdout
        return

    table = Table(show_header=True, header_style="bold cyan")
    for col in columns:
        table.add_column(col.replace("_", " ").title())

    for row in data:
        table.add_row(*[str(row.get(k, "")) for k in columns])

    console.print(table)

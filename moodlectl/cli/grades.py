from __future__ import annotations

import typer
from rich.console import Console

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import grades as grades_feature
from moodlectl.output.formatters import print_table

app = typer.Typer(help="Grade commands")
console = Console()


@app.command("show")
def show_grades(
    course: int = typer.Option(..., "--course", help="Course ID"),
    name: str = typer.Option("", "--name", "-n", help="Filter by student name (partial match)"),
    full: bool = typer.Option(False, "--full", "-f", help="Show all grade items (scrollable)"),
    output: str = typer.Option("table", "--output", "-o", help="table, json, csv"),
):
    """Show grades for all students in a course.

    Default table shows name + course total. Use --full for all columns, --output csv to export.

    Examples:
      moodlectl grades show --course 568
      moodlectl grades show --course 568 --full
      moodlectl grades show --course 568 --name "Abdulrahman"
      moodlectl grades show --course 568 --output csv > grades.csv
    """
    client = MoodleClient.from_config(Config.load())
    report = grades_feature.get_grade_report(client, course, name=name)

    rows = report["rows"]
    columns = report["columns"]

    if not rows:
        console.print("[yellow]No grades found.[/yellow]")
        raise typer.Exit()

    # columns[0] = "First name / Last name", [1] = "Email address", [-1] = "Course total"
    grade_cols = columns[2:]
    total_col = columns[-1]

    if output != "table":
        # CSV / JSON: full column names (including Arabic)
        print_table(rows, columns=["fullname", "email"] + grade_cols, fmt=output)
        return

    # For full view use longer names (more space available in vertical layout)
    col_map = grades_feature.shorten_columns(grade_cols, max_len=50 if full else 22)

    display_rows = []
    for row in rows:
        d = {"fullname": row["fullname"]}
        for orig, short in col_map.items():
            d[short] = row.get(orig, "-")
        display_rows.append(d)

    all_short = list(col_map.values())
    short_total = col_map.get(total_col, total_col)

    if full:
        # Vertical layout: one section per student, grade items listed as rows
        from rich.panel import Panel
        from rich.table import Table

        for row in display_rows:
            tbl = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
            tbl.add_column("Item", style="dim", min_width=30)
            tbl.add_column("Score", justify="right")
            for orig, short in col_map.items():
                score = row.get(short, "-")
                style = "bold green" if short == short_total else ""
                tbl.add_row(short, f"[{style}]{score}[/{style}]" if style else score)
            console.print(Panel(tbl, title=f"[bold]{row['fullname']}[/bold]", expand=False))
    elif len(all_short) > 8:
        console.print(
            f"[dim]{len(all_short)} grade items — use [bold]--full[/bold] to see all "
            f"or [bold]--output csv[/bold] to export.[/dim]\n"
        )
        print_table(display_rows, columns=["fullname", short_total], fmt="table")
    else:
        print_table(display_rows, columns=["fullname"] + all_short, fmt="table")

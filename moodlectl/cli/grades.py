from __future__ import annotations

from typing import Optional, cast

import typer
from rich.console import Console

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import grades as grades_feature
from moodlectl.output.formatters import print_table
from moodlectl.types import CourseId, GradeReport, OutputFmt

app = typer.Typer(help="Grade report commands — view and analyse student grades.")
console = Console()


@app.command("show")
def show_grades(
        course: Optional[int] = typer.Option(None, "--course", help="Course ID. Omit to show all enrolled courses."),
        name: str = typer.Option("", "--name", "-n", help="Filter by student name (partial match)."),
        full: bool = typer.Option(False, "--full", "-f", help="Show all grade items as a wide table."),
        cards: bool = typer.Option(False, "--cards", help="Show one panel per student listing all grade items."),
        include_hidden: bool = typer.Option(
            False,
            "--include-hidden",
            help="Include grade items whose activity is hidden from students (default: excluded).",
        ),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """Show the grade report for all students in a course.

    Default view: name + course total only (summary).
    --full : wide table with every grade item as a column.
    --cards: one Rich panel per student showing all grade items vertically.
    Omit --course to iterate over all your courses.

    Use --output csv to export all columns in UTF-8 (Excel-compatible).

    Examples:
      moodlectl grades show
      moodlectl grades show --course 568
      moodlectl grades show --course 568 --full
      moodlectl grades show --course 568 --cards
      moodlectl grades show --course 568 --name "Aljawhara"
      moodlectl grades show --course 568 --name "Aljawhara" --cards
      moodlectl grades show --course 568 --output csv > grades.csv
    """
    client = MoodleClient.from_config(Config.load())

    course_ids = [CourseId(course)] if course is not None else [c["id"] for c in client.get_courses()]

    reports: list[tuple[CourseId, GradeReport]] = []
    for cid in course_ids:
        report = grades_feature.get_grade_report(client, cid, name=name, include_hidden=include_hidden)
        reports.append((cid, report))

    # For multi-course csv/json, merge all rows into one flat list
    if output != "table" and len(reports) > 1:
        all_rows: list[dict[str, str | int]] = []
        for cid, report in reports:
            for row in report["rows"]:
                all_rows.append({"course_id": cid, **row})
        if all_rows:
            cols = ["course_id", "fullname", "email"] + reports[0][1]["columns"][2:]
            print_table(all_rows, columns=cols, fmt=cast(OutputFmt, output))
        return

    for cid, report in reports:
        _print_report(console, report, cid if course is None else None, full, cards, cast(OutputFmt, output))


@app.command("stats")
def grade_stats(
        course: int = typer.Option(..., "--course", "-c", help="Course ID (from `courses list`)."),
        name: str = typer.Option("", "--name", "-n",
                                 help="Filter by student name before computing stats (partial match)."),
):
    """Show grade statistics for a course: mean, median, std dev, min, max.

    Statistics are computed on the Course Total column of the grade report.
    Use --name to compute stats for a specific subset of students.

    Examples:
      moodlectl grades stats --course 568
      moodlectl grades stats --course 568 --name "Group A"
    """
    client = MoodleClient.from_config(Config.load())

    try:
        report = grades_feature.get_grade_report(client, CourseId(course), name=name)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    stats = grades_feature.compute_stats(report)

    if stats["count"] == 0:
        console.print("[yellow]No numeric grades found in the course total column.[/yellow]")
        raise typer.Exit()

    console.print(f"\n[bold]Grade statistics — {stats['column']}[/bold]\n")
    rows: list[dict[str, str]] = [
        {"metric": "Students", "value": str(stats["count"])},
        {"metric": "Mean", "value": str(stats["mean"])},
        {"metric": "Median", "value": str(stats["median"])},
        {"metric": "Std deviation", "value": str(stats["std_dev"])},
        {"metric": "Min", "value": str(stats["min"])},
        {"metric": "Max", "value": str(stats["max"])},
    ]
    print_table(rows, columns=["metric", "value"], fmt="table")


# ── internal helpers ──────────────────────────────────────────────────────────

def _print_report(
        console: Console,
        report: GradeReport,
        course_id: CourseId | None,
        full: bool,
        cards: bool,
        output: OutputFmt,
) -> None:
    """Render a single course grade report in the requested display mode."""
    rows = report["rows"]
    columns = report["columns"]

    if not rows:
        label = f"course {course_id}" if course_id is not None else "any course"
        console.print(f"[yellow]No grades found for {label}.[/yellow]")
        return

    if course_id is not None:
        console.print(f"\n[bold cyan]Course {course_id}[/bold cyan]")

    # columns[0] = student name, [1] = email, [-1] = Course total
    grade_cols = columns[2:]
    total_col = columns[-1]

    if output != "table":
        print_table(rows, columns=["fullname", "email"] + grade_cols, fmt=output)
        return

    col_map: dict[str, str] = grades_feature.shorten_columns(grade_cols, max_len=50 if (full or cards) else 22)

    display_rows: list[dict[str, str | int]] = []
    for row in rows:
        d: dict[str, str | int] = {"fullname": str(row.get("fullname", ""))}
        for orig, short in col_map.items():
            d[short] = str(row.get(orig, "-"))
        display_rows.append(d)

    all_short: list[str] = list(col_map.values())
    short_total: str = col_map.get(total_col, total_col)

    if cards:
        from rich.panel import Panel
        from rich.table import Table

        for row in display_rows:
            tbl = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
            tbl.add_column("Item", style="dim", min_width=30)
            tbl.add_column("Score", justify="right")
            for orig, short in col_map.items():
                score = str(row.get(short, "-"))
                style = "bold green" if short == short_total else ""
                tbl.add_row(short, f"[{style}]{score}[/{style}]" if style else score)
            console.print(Panel(tbl, title=f"[bold]{row.get('fullname', '')}[/bold]", expand=False))

    elif full:
        print_table(display_rows, columns=["fullname"] + all_short, fmt="table")

    else:
        # Summary: name + course total only, with a hint about the other views
        console.print(
            f"[dim]{len(all_short)} grade item(s) — use [bold]--full[/bold] to see all columns "
            f"or [bold]--cards[/bold] for a per-student view.[/dim]\n"
        )
        print_table(display_rows, columns=["fullname", short_total], fmt="table")

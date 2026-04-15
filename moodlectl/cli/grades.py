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
    course: int = typer.Option(None, "--course", help="Course ID. Omit to show all courses."),
    name: str = typer.Option("", "--name", "-n", help="Filter by student name (partial match)"),
    full: bool = typer.Option(False, "--full", "-f", help="Show all grade items as a wide table"),
    cards: bool = typer.Option(False, "--cards", help="Show one card per student with all grade items"),
    output: str = typer.Option("table", "--output", "-o", help="table, json, csv"),
):
    """Show grades for all students in a course.

    Default view shows name + course total only.
    Use --full for a wide table with all grade items, --cards for one panel per student.
    Omit --course to show all your courses at once.

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

    if course is None:
        course_ids = [c["id"] for c in client.get_courses()]
    else:
        course_ids = [course]

    reports = []
    for cid in course_ids:
        report = grades_feature.get_grade_report(client, cid, name=name)
        reports.append((cid, report))

    # For multi-course output mode, merge all rows for csv/json
    if output != "table" and len(reports) > 1:
        all_rows: list[dict] = []
        for cid, report in reports:
            for row in report["rows"]:
                all_rows.append({"course_id": cid, **row})
        if all_rows:
            cols = ["course_id", "fullname", "email"] + reports[0][1]["columns"][2:]
            print_table(all_rows, columns=cols, fmt=output)
        return

    # Single report path (reused for both single-course and per-course table display)
    for cid, report in reports:
        _print_report(console, report, cid if course is None else None, full, cards, output, grades_feature)



def _print_report(console, report, course_id, full, cards, output, grades_feature):
    rows = report["rows"]
    columns = report["columns"]

    if not rows:
        if course_id is not None:
            console.print(f"[yellow]No grades found for course {course_id}.[/yellow]")
        else:
            console.print("[yellow]No grades found.[/yellow]")
        return

    if course_id is not None:
        console.print(f"\n[bold cyan]Course {course_id}[/bold cyan]")

    # columns[0] = "First name / Last name", [1] = "Email address", [-1] = "Course total"
    grade_cols = columns[2:]
    total_col = columns[-1]

    if output != "table":
        print_table(rows, columns=["fullname", "email"] + grade_cols, fmt=output)
        return

    col_map = grades_feature.shorten_columns(grade_cols, max_len=50 if (full or cards) else 22)

    display_rows = []
    for row in rows:
        d = {"fullname": row["fullname"]}
        for orig, short in col_map.items():
            d[short] = row.get(orig, "-")
        display_rows.append(d)

    all_short = list(col_map.values())
    short_total = col_map.get(total_col, total_col)

    if cards:
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
    elif full:
        print_table(display_rows, columns=["fullname"] + all_short, fmt="table")
    else:
        console.print(
            f"[dim]{len(all_short)} grade items — use [bold]--full[/bold] to see all columns "
            f"or [bold]--cards[/bold] for per-student view.[/dim]\n"
        )
        print_table(display_rows, columns=["fullname", short_total], fmt="table")

from __future__ import annotations

import sys

import typer

# Force UTF-8 stdout so Arabic/Unicode in assignment names and course names
# don't crash on Windows terminals that default to cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from moodlectl.cli import (
    analytics,
    announcements,
    assignments,
    auth,
    content,
    courses,
    grades,
    grading,
    messages,
)

app = typer.Typer(
    name="moodlectl",
    help=(
        "Moodle LMS automation for university instructors.\n\n"
        "Run `moodlectl summary` for a quick overview of upcoming deadlines.\n"
        "Run `moodlectl auth check` to verify your session before long operations."
    ),
    no_args_is_help=True,
)

app.add_typer(analytics.app, name="analytics")
app.add_typer(auth.app, name="auth")
app.add_typer(content.app, name="content")
app.add_typer(courses.app, name="courses")
app.add_typer(grades.app, name="grades")
app.add_typer(assignments.app, name="assignments")
app.add_typer(grading.app, name="grading")
app.add_typer(messages.app, name="messages")
app.add_typer(announcements.app, name="announcements")


@app.command("summary")
def summary():
    """Quick overview: enrolled courses and assignments due in the next 7 days.

    This is intentionally fast — it only checks due dates, not submission or
    grading counts. For the full picture run:
      moodlectl assignments ungraded    — all submitted but ungraded work
      moodlectl assignments missing     — all students who haven't submitted
      moodlectl assignments due-soon    — customise the look-ahead window

    Examples:
      moodlectl summary
    """
    from rich.console import Console
    from rich.table import Table

    from moodlectl.client import MoodleClient
    from moodlectl.config import Config
    from moodlectl.features import assignments as assignments_feature

    console = Console(legacy_windows=False)
    client = MoodleClient.from_config(Config.load())

    all_courses = client.get_courses()
    course_map = {c["id"]: c for c in all_courses}
    course_ids = list(course_map.keys())

    console.print(f"\n[bold]Enrolled courses:[/bold] {len(all_courses)}")

    # Assignments due within the next 7 days (date check only — no submission fetching)
    due_soon = assignments_feature.get_due_soon(client, course_ids, course_map, days=7)

    if due_soon:
        console.print(f"\n[bold yellow]{len(due_soon)} assignment(s) due in the next 7 days:[/bold yellow]\n")
        tbl = Table(show_header=True, header_style="bold")
        tbl.add_column("Course")
        tbl.add_column("Assignment")
        tbl.add_column("Due date")
        tbl.add_column("Days left", justify="right")
        tbl.add_column("Submitted", justify="right")
        for a in due_soon:
            tbl.add_row(
                a["course"],
                a["assignment"],
                a["due_date"],
                str(a["days_left"]),
                str(a["submitted"]),
            )
        console.print(tbl)
    else:
        console.print("\n[green]No assignments due in the next 7 days.[/green]")

    console.print()
    console.print("[dim]Run [bold]moodlectl assignments ungraded[/bold]   — all ungraded submissions.[/dim]")
    console.print("[dim]Run [bold]moodlectl assignments missing[/bold]    — all missing submissions.[/dim]")
    console.print("[dim]Run [bold]moodlectl assignments due-soon --days 14[/bold] to widen the window.[/dim]\n")


if __name__ == "__main__":
    app()

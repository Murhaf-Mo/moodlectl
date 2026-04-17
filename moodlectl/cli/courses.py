from __future__ import annotations

from typing import Optional, cast

import typer
from rich.console import Console
from rich.table import Table

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import courses as courses_feature
from moodlectl.output.formatters import print_table
from moodlectl.types import CourseId, OutputFmt

app = typer.Typer(help="Course commands — list, settings, participants, and inactive students.")
console = Console(legacy_windows=False)

_COURSE_OPT = typer.Option(..., "--course", "-c", help="Course ID (from `courses list`).")


@app.command("settings")
def course_settings(
    course: int = _COURSE_OPT,
) -> None:
    """Show all editable settings for a course.

    Displays every setting that can be changed via `courses set`.
    Use this to inspect the current configuration before editing.

    Examples:
      moodlectl courses settings --course 581
    """
    client = MoodleClient.from_config(Config.load())
    try:
        settings = courses_feature.get_course_settings(client, CourseId(course))
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    tbl = Table(title=f"Settings for course {course}", show_header=True, header_style="bold")
    tbl.add_column("Field", style="bold cyan")
    tbl.add_column("Value")
    for key, val in settings.items():
        display = str(val) if val not in ("", [], None) else "[dim](not set)[/dim]"
        tbl.add_row(key, display)
    console.print(tbl)


@app.command("set")
def set_course_setting(
    course: int = _COURSE_OPT,
    field: str = typer.Option(..., "--field", "-f", help="Setting name (from `courses settings`)."),
    value: str = typer.Option(..., "--value", "-v", help="New value."),
) -> None:
    """Change a single setting on a course.

    Use `courses settings` to see available field names and current values.
    Dates use 'YYYY-MM-DD HH:MM' format.

    Examples:
      moodlectl courses set --course 581 --field fullname --value "New Course Name"
      moodlectl courses set --course 581 --field visible --value 1
      moodlectl courses set --course 581 --field end_date --value "2027-01-15 00:00"
      moodlectl courses set --course 581 --field enable_completion --value 1
      moodlectl courses set --course 581 --field tags --value "tag1,tag2"
    """
    client = MoodleClient.from_config(Config.load())
    try:
        courses_feature.set_course_setting(client, CourseId(course), field, value)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Course {course} field {field!r} updated.[/green]")


@app.command("list")
def list_courses(
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """List all your enrolled courses.

    The id column is the course ID used by all --course flags across the tool.

    Examples:
      moodlectl courses list
      moodlectl courses list --output csv > courses.csv
    """
    client = MoodleClient.from_config(Config.load())
    data = courses_feature.list_courses(client)
    print_table(data, columns=["id", "fullname", "shortname"], fmt=cast(OutputFmt, output))


@app.command("participants")
def participants(
        course_id: Optional[int] = typer.Option(
            None, "--id", "--course", "-c",
            help="Course ID (from `courses list`). Omit to show participants for all courses."
        ),
        role: str = typer.Option("", "--role", "-r", help="Filter by role, e.g. student or teacher (partial match)."),
        name: str = typer.Option("", "--name", "-n", help="Filter by name (partial match)."),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """Show participants for one course or all courses.

    --id and --course are aliases — use whichever is clearer.
    The id column in the output is the user ID used by grading and messaging commands.

    Examples:
      moodlectl courses participants --course 568
      moodlectl courses participants --role student
      moodlectl courses participants --course 568 --name "Ali"
      moodlectl courses participants --course 568 --output csv > students.csv
    """
    client = MoodleClient.from_config(Config.load())

    if course_id:
        data = courses_feature.get_participants(client, CourseId(course_id), role=role, name=name)
        print_table(data, columns=["id", "fullname", "email", "roles", "lastaccess"], fmt=cast(OutputFmt, output))
    else:
        all_data = courses_feature.get_all_participants(client, role=role, name=name)
        courses = courses_feature.list_courses(client)
        course_names = {c["id"]: c["fullname"] for c in courses}

        for cid, members in all_data.items():
            console.print(f"\n[bold cyan]{course_names.get(cid, f'Course {cid}')}[/bold cyan]")
            print_table(members, columns=["id", "fullname", "email", "roles"], fmt=cast(OutputFmt, output))


@app.command("inactive")
def inactive_students(
        course_id: Optional[int] = typer.Option(
            None, "--course", "-c",
            help="Course ID (from `courses list`). Omit to scan all your courses."
        ),
        days: int = typer.Option(
            14, "--days", "-d",
            help="Minimum days since last access (default: 14). Students inactive for at least this long are shown."
        ),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """Show students who have not accessed the course in at least N days.

    Omit --course to scan all your enrolled courses at once.
    Uses Moodle's lastaccess text (e.g. "3 days 14 hours") on a best-effort basis.
    Students whose lastaccess cannot be parsed are also included (shown as "?")
    so nothing is silently dropped.

    Useful for identifying at-risk students before a deadline.

    Examples:
      moodlectl courses inactive
      moodlectl courses inactive --days 7
      moodlectl courses inactive --course 568
      moodlectl courses inactive --course 568 --days 7
      moodlectl courses inactive --output csv > inactive.csv
    """
    client = MoodleClient.from_config(Config.load())

    try:
        if course_id is not None:
            # Single course — omit the 'course' column, it's implied
            inactive = courses_feature.get_inactive_students(client, course_id=CourseId(course_id), days=days)
            columns = ["user_id", "fullname", "email", "lastaccess", "inactive_days"]
        else:
            # All courses — include the 'course' column for context
            inactive = courses_feature.get_all_inactive_students(client, days=days)
            columns = ["course", "user_id", "fullname", "email", "lastaccess", "inactive_days"]
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if not inactive:
        scope = f"course {course_id}" if course_id else "any of your courses"
        console.print(f"[green]All students have accessed {scope} in the last {days} day(s).[/green]")
        raise typer.Exit()

    scope_label = f"course {course_id}" if course_id else "all courses"
    console.print(f"\n[yellow]{len(inactive)} student(s) inactive for {days}+ day(s) across {scope_label}:[/yellow]\n")
    print_table(inactive, columns=columns, fmt=cast(OutputFmt, output))

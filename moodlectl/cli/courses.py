from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import courses as courses_feature
from moodlectl.output.formatters import print_table

app = typer.Typer(help="Course management commands")
console = Console()


@app.command("list")
def list_courses(
    output: str = typer.Option("table", "--output", "-o", help="table, json, csv"),
):
    """List all your enrolled courses."""
    client = MoodleClient.from_config(Config.load())
    data = courses_feature.list_courses(client)
    print_table(data, columns=["id", "fullname", "shortname"], fmt=output)


@app.command("participants")
def participants(
    course_id: Optional[int] = typer.Option(None, "--id", help="Course ID. Omit for all courses."),
    role: str = typer.Option("", "--role", "-r", help="Filter by role, e.g. student, teacher"),
    name: str = typer.Option("", "--name", "-n", help="Filter by name (partial match)"),
    output: str = typer.Option("table", "--output", "-o", help="table, json, csv"),
):
    """Show participants for one course or all courses.

    Examples:
      moodlectl courses participants --id 568
      moodlectl courses participants --role student
      moodlectl courses participants --id 568 --name "Ali"
    """
    client = MoodleClient.from_config(Config.load())

    if course_id:
        data = courses_feature.get_participants(client, course_id, role=role, name=name)
        print_table(data, columns=["id", "fullname", "email", "roles", "lastaccess"], fmt=output)
    else:
        all_data = courses_feature.get_all_participants(client, role=role, name=name)
        courses = courses_feature.list_courses(client)
        course_names = {c["id"]: c["fullname"] for c in courses}

        for cid, members in all_data.items():
            console.print(f"\n[bold cyan]{course_names.get(cid, f'Course {cid}')}[/bold cyan]")
            print_table(members, columns=["id", "fullname", "email", "roles"], fmt=output)

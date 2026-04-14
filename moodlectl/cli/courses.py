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
    output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, csv"),
):
    """List all your enrolled courses."""
    client = MoodleClient.from_config(Config.load())
    data = courses_feature.list_courses(client)
    print_table(data, columns=["id", "fullname", "shortname"], fmt=output)


@app.command("participants")
def participants(
    course_id: Optional[int] = typer.Option(None, "--id", help="Course ID. Omit for all courses."),
    output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, csv"),
):
    """Show participants for one course or all courses."""
    client = MoodleClient.from_config(Config.load())

    if course_id:
        data = courses_feature.get_participants(client, course_id)
        print_table(data, columns=["id", "fullname", "email", "roles", "lastaccess"], fmt=output)
    else:
        all_data = courses_feature.get_all_participants(client)
        courses = courses_feature.list_courses(client)
        course_names = {c["id"]: c["fullname"] for c in courses}

        for cid, members in all_data.items():
            console.print(f"\n[bold cyan]{course_names.get(cid, f'Course {cid}')}[/bold cyan]")
            print_table(members, columns=["id", "fullname", "email", "roles"], fmt=output)

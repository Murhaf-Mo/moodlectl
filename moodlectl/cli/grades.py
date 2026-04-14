from __future__ import annotations

import typer

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.output.formatters import console

app = typer.Typer(help="Grade commands")


@app.command("show")
def show_grades(
    course: int = typer.Option(..., "--course", help="Course ID"),
    student: int = typer.Option(0, "--student", help="Student user ID (0 = all)"),
):
    """Show grade items for a course."""
    client = MoodleClient.from_config(Config.load())
    data = client.get_grades(course, student)
    console.print_json(__import__("json").dumps(data, default=str))

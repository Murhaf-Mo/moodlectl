from __future__ import annotations

import typer

from moodlectl.cli import courses, grades, messages, reports

app = typer.Typer(
    name="moodlectl",
    help="Moodle LMS automation tool for university instructors.",
    no_args_is_help=True,
)

app.add_typer(courses.app, name="courses")
app.add_typer(grades.app, name="grades")
app.add_typer(messages.app, name="messages")
app.add_typer(reports.app, name="reports")


if __name__ == "__main__":
    app()

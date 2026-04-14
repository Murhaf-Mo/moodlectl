from __future__ import annotations

import sys
import typer

# Force UTF-8 stdout so Arabic/Unicode in assignment names and course names
# don't crash on Windows terminals that default to cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from moodlectl.cli import assignments, courses, grades, grading, messages, reports

app = typer.Typer(
    name="moodlectl",
    help="Moodle LMS automation tool for university instructors.",
    no_args_is_help=True,
)

app.add_typer(courses.app, name="courses")
app.add_typer(grades.app, name="grades")
app.add_typer(assignments.app, name="assignments")
app.add_typer(grading.app, name="grading")
app.add_typer(messages.app, name="messages")
app.add_typer(reports.app, name="reports")


if __name__ == "__main__":
    app()

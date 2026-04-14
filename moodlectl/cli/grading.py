from __future__ import annotations

import typer
from rich.console import Console

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import grading as grading_feature

app = typer.Typer(help="Grade submission commands")
console = Console(legacy_windows=False)


@app.command("submit")
def submit_grade(
    cmid: int = typer.Option(..., "--assignment", "-a", help="Assignment cmid (from `assignments list`)"),
    user: int = typer.Option(..., "--student", "-s", help="Student user ID (from `courses participants`)"),
    grade: float = typer.Option(..., "--grade", "-g", help="Grade value (must be within the assignment's grade scale)"),
    feedback: str = typer.Option("", "--feedback", "-f", help="Optional written feedback for the student"),
    notify: bool = typer.Option(False, "--notify", help="Send the student a notification email"),
):
    """Submit a grade for a student on an assignment.

    The grade must be within the assignment's configured grade scale
    (shown as 'Grade out of X' in Moodle). Use `assignments list` to find
    the assignment cmid and `courses participants` to find the student ID.

    Examples:
      moodlectl grading submit --assignment 18002 --student 1557 --grade 10
      moodlectl grading submit -a 18002 -s 1557 -g 8.5 --feedback "Good work overall."
      moodlectl grading submit -a 18002 -s 1557 -g 10 --notify
    """
    client = MoodleClient.from_config(Config.load())

    console.print(f"Submitting grade [bold]{grade}[/bold] for student [bold]{user}[/bold] on assignment [bold]{cmid}[/bold]…")

    try:
        result = grading_feature.submit_grade(
            client,
            cmid=cmid,
            user_id=user,
            grade=grade,
            feedback=feedback,
            notify_student=notify,
        )
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    grade_max = result["grade_max"]
    grade_pct = result["grade_pct"]
    console.print(
        f"[green]Saved.[/green] Grade: [bold]{result['grade']} / {grade_max}[/bold]"
        + (f" ({grade_pct}%)" if grade_pct is not None else "")
    )

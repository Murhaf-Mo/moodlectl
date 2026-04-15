from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import cast

import typer
from rich.console import Console

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import assignments as assignments_feature
from moodlectl.features import grading as grading_feature
from moodlectl.output.formatters import print_table
from moodlectl.types import Cmid, OutputFmt, UserId

app = typer.Typer(help="Grade submission commands — submit, inspect, batch-grade, and guided grading.")
console = Console(legacy_windows=False)


@app.command("show")
def show_grade(
        cmid: int = typer.Option(..., "--assignment", "-a", help="Assignment cmid (from `assignments list`)."),
        user: int = typer.Option(..., "--student", "-s", help="Student user ID (from `courses participants`)."),
):
    """Show the current grade and feedback for a student without changing anything.

    Use this before `grading submit` to confirm what was previously entered.
    The assignment cmid comes from `assignments list`; the student ID from `courses participants`.

    Examples:
      moodlectl grading show --assignment 18002 --student 1557
    """
    client = MoodleClient.from_config(Config.load())

    try:
        _, context_id = client.get_assignment_internal_id(Cmid(cmid))
        fields = client.get_grade_form_fragment(context_id, UserId(user))
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    grade = fields.get("grade", "—")
    grade_max = fields.get("__grade_max__", "?")
    feedback = fields.get("assignfeedbackcomments_editor[text]", "").strip() or "—"

    console.print(f"Assignment : [bold]{cmid}[/bold]")
    console.print(f"Student    : [bold]{user}[/bold]")
    console.print(f"Grade      : [bold]{grade} / {grade_max}[/bold]")
    console.print(f"Feedback   : {feedback}")


@app.command("submit")
def submit_grade(
        cmid: int = typer.Option(..., "--assignment", "-a", help="Assignment cmid (from `assignments list`)."),
        user: int = typer.Option(..., "--student", "-s", help="Student user ID (from `courses participants`)."),
        grade: float = typer.Option(..., "--grade", "-g",
                                    help="Grade value (must be within the assignment's grade scale)."),
        feedback: str = typer.Option("", "--feedback", "-f", help="Optional written feedback for the student."),
        notify: bool = typer.Option(False, "--notify", help="Send the student an email notification after grading."),
):
    """Submit a grade for a student on an assignment.

    The grade must be within the assignment's configured scale (shown as "Grade out of X").
    Use `grading show` first to see the current grade before overwriting.
    Use `assignments list` to find the cmid; `courses participants` to find the student ID.

    Examples:
      moodlectl grading submit --assignment 18002 --student 1557 --grade 10
      moodlectl grading submit -a 18002 -s 1557 -g 8.5 --feedback "Good work overall."
      moodlectl grading submit -a 18002 -s 1557 -g 10 --notify
    """
    client = MoodleClient.from_config(Config.load())

    # Look up student's name from the submissions list for a friendlier confirmation message
    student_name = f"ID {user}"
    try:
        subs = client.get_assignment_submissions(Cmid(cmid))
        match = next((s for s in subs if s["user_id"] == UserId(user)), None)
        if match:
            student_name = match["fullname"]
    except Exception:
        pass  # Name lookup is best-effort; fall back to ID

    console.print(
        f"Grading [bold]{student_name}[/bold] on assignment [bold]{cmid}[/bold] "
        f"— grade [bold]{grade}[/bold]…"
    )

    try:
        result = grading_feature.submit_grade(
            client,
            cmid=Cmid(cmid),
            user_id=UserId(user),
            grade=grade,
            feedback=feedback,
            notify_student=notify,
        )
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    grade_max = result["grade_max"]
    grade_pct = result["grade_pct"]

    console.print(f"Student    : [bold]{student_name}[/bold]  (ID {user})")
    console.print(
        f"Grade      : [bold]{result['grade']} / {grade_max}[/bold]"
        + (f"  ({grade_pct}%)" if grade_pct is not None else "")
    )
    if feedback:
        console.print(f"Feedback   : {feedback}")
    console.print("[green]Saved.[/green]")


@app.command("batch")
def batch_grade(
        cmid: int = typer.Option(..., "--assignment", "-a", help="Assignment cmid (from `assignments list`)."),
        file: Path = typer.Option(..., "--file", "-f",
                                  help="CSV file with columns: user_id, grade, feedback (optional)."),
        dry_run: bool = typer.Option(
            False, "--dry-run",
            help="Validate the CSV and show what would be submitted without writing anything."
        ),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """Submit grades from a CSV file — one row per student.

    CSV format (header row required):
      user_id,grade,feedback
      1557,8.5,Good work overall.
      1612,10,Excellent.

    The user_id comes from `courses participants`. The grade must be within the
    assignment's configured scale. The feedback column is optional.

    Use --dry-run first to validate the file and preview all submissions before
    committing. Notifications are not sent during batch grading.

    Examples:
      moodlectl grading batch --assignment 18002 --file grades.csv --dry-run
      moodlectl grading batch --assignment 18002 --file grades.csv
      moodlectl grading batch -a 18002 -f grades.csv --output csv > results.csv
    """
    if not file.exists():
        console.print(f"[red]File not found:[/red] {file}")
        raise typer.Exit(1)

    # Parse CSV — accept both comma and tab delimiters
    try:
        text = file.read_text(encoding="utf-8-sig")  # utf-8-sig strips Excel BOM
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as exc:
        console.print(f"[red]Could not read CSV:[/red] {exc}")
        raise typer.Exit(1)

    if not rows:
        console.print("[yellow]CSV file is empty.[/yellow]")
        raise typer.Exit()

    required = {"user_id", "grade"}
    missing_cols = required - set(rows[0].keys())
    if missing_cols:
        console.print(f"[red]CSV is missing required columns:[/red] {', '.join(missing_cols)}")
        console.print("Expected header: user_id,grade,feedback")
        raise typer.Exit(1)

    client = MoodleClient.from_config(Config.load())

    if dry_run:
        console.print(f"[dim](dry run) {len(rows)} row(s) in {file.name} — nothing will be submitted.[/dim]\n")

    results = grading_feature.batch_grade(client, cmid=Cmid(cmid), rows=rows, dry_run=dry_run)

    ok = sum(1 for r in results if r.get("ok") is True or r.get("ok") == "(dry run)")
    failed = sum(1 for r in results if r.get("ok") is False)

    print_table(results, columns=["user_id", "grade", "grade_max", "grade_pct", "ok", "error"],
                fmt=cast(OutputFmt, output))

    if dry_run:
        console.print(f"\n[dim](dry run) {len(results)} row(s) validated. Run without --dry-run to submit.[/dim]")
    else:
        console.print(f"\n[green]{ok}[/green] submitted" + (f", [red]{failed}[/red] failed." if failed else "."))


@app.command("next")
def next_to_grade(
        cmid: int = typer.Option(..., "--assignment", "-a", help="Assignment cmid (from `assignments list`)."),
        notify: bool = typer.Option(False, "--notify", help="Send the student an email notification after each grade."),
):
    """Interactively grade ungraded students one at a time.

    Shows each ungraded student's name, files, and current grade status, then
    prompts you to enter a grade and optional feedback. Progress is saved after
    each student — press Ctrl+C to stop at any time.

    Type 'skip' at the grade prompt to move to the next student without grading.

    Examples:
      moodlectl grading next --assignment 18002
      moodlectl grading next --assignment 18002 --notify
    """
    client = MoodleClient.from_config(Config.load())

    try:
        submissions = client.get_assignment_submissions(Cmid(cmid))
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    ungraded = [s for s in submissions if assignments_feature.is_ungraded(s)]

    if not ungraded:
        console.print("[green]All submissions are already graded.[/green]")
        raise typer.Exit()

    # Read grade_max once from the first student's grading fragment
    grade_max = None
    try:
        _, context_id = client.get_assignment_internal_id(Cmid(cmid))
        fragment = client.get_grade_form_fragment(context_id, ungraded[0]["user_id"])
        grade_max = fragment.get("__grade_max__")
    except Exception:
        pass  # grade_max stays None; prompts will omit the "out of X" hint

    total = len(ungraded)
    console.print(f"\nAssignment [bold]{cmid}[/bold] — [bold]{total}[/bold] ungraded submission(s)\n")

    graded_count = 0
    for i, sub in enumerate(ungraded, 1):
        console.rule(f"[bold]{i} / {total}[/bold]")
        console.print(f"Student : [bold]{sub['fullname']}[/bold]  (ID {sub['user_id']})")
        console.print(f"Email   : {sub['email']}")
        if sub["files"]:
            console.print(f"Files   : {', '.join(f['filename'] for f in sub['files'])}")

        grade_prompt = f"Grade (out of {grade_max}, or 'skip')" if grade_max else "Grade (or 'skip')"

        try:
            grade_input = typer.prompt(grade_prompt)
            if grade_input.strip().lower() == "skip":
                console.print("[dim]Skipped.[/dim]\n")
                continue

            grade = float(grade_input)
            feedback = typer.prompt("Feedback (Enter to skip)", default="")

            result = grading_feature.submit_grade(
                client,
                cmid=Cmid(cmid),
                user_id=sub["user_id"],
                grade=grade,
                feedback=feedback,
                notify_student=notify,
            )
            grade_pct = result["grade_pct"]
            console.print(
                f"[green]Saved.[/green] {result['grade']} / {result['grade_max']}"
                + (f"  ({grade_pct}%)" if grade_pct is not None else "")
                + "\n"
            )
            graded_count += 1

        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped.[/yellow]")
            break
        except ValueError:
            console.print("[red]Invalid grade — enter a number or 'skip'.[/red]")
            continue
        except RuntimeError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            continue

    console.print(f"\n[bold]Session complete.[/bold] Graded {graded_count} of {total} student(s).")

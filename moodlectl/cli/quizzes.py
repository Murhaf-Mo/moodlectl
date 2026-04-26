from __future__ import annotations

from typing import cast

import typer
from rich.console import Console

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import content as content_feature
from moodlectl.features import quizzes as quizzes_feature
from moodlectl.output.formatters import print_table
from moodlectl.types import Cmid, CourseId, CourseMap, OutputFmt

app = typer.Typer(help="Quiz commands — list, attempts, results, delete.")
console = Console(legacy_windows=False)


def _load(course: tuple[int, ...]) -> tuple[MoodleClient, list[CourseId], CourseMap]:
    client = MoodleClient.from_config(Config.load())
    all_courses = client.get_courses()
    course_map: CourseMap = {c["id"]: c for c in all_courses}
    course_ids = [CourseId(c) for c in course] if course else list(course_map.keys())
    return client, course_ids, course_map


# ── list ──────────────────────────────────────────────────────────────────────

@app.command("list")
def list_quizzes(
        course: list[int] = typer.Option(
            None, "--course", "-c", help="Course ID (repeatable). Omit for all your courses."
        ),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """List quizzes across your courses.

    The cmid column is the ID used by all other quiz commands.

    Examples:
      moodlectl quizzes list
      moodlectl quizzes list --course 83
      moodlectl quizzes list --output csv > quizzes.csv
    """
    client, course_ids, course_map = _load(tuple(course or []))
    quizzes = quizzes_feature.list_quizzes(client, course_ids)

    if not quizzes:
        console.print("[yellow]No quizzes found.[/yellow]")
        raise typer.Exit()

    rows: list[dict[str, str | int]] = []
    for q in quizzes:
        course_info = course_map.get(q["course_id"])
        rows.append({
            "cmid": q["cmid"],
            "course": course_info["shortname"] if course_info else str(q["course_id"]),
            "quiz": q["name"],
            "visible": "yes" if q["visible"] else "hidden",
        })
    print_table(rows, columns=["cmid", "course", "quiz", "visible"], fmt=cast(OutputFmt, output))


# ── attempts ──────────────────────────────────────────────────────────────────

@app.command("attempts")
def list_attempts(
        cmid: int = typer.Option(..., "--quiz", "-q", help="Quiz cmid (from `quizzes list`)."),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """List every attempt for one quiz (one row per attempt).

    Includes student, state (Finished/In progress/Overdue/...), start/end times,
    duration, and the grade. Use `quizzes results` for one row per student.

    Examples:
      moodlectl quizzes attempts --quiz 978
      moodlectl quizzes attempts -q 978 --output csv > attempts.csv
    """
    client = MoodleClient.from_config(Config.load())
    try:
        attempts = quizzes_feature.get_attempts(client, Cmid(cmid))
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if not attempts:
        console.print("[yellow]No attempts found for this quiz.[/yellow]")
        raise typer.Exit()

    rows: list[dict[str, str | int]] = []
    for a in attempts:
        rows.append({
            "attempt_id": a["attempt_id"],
            "user_id": a["user_id"] if a["user_id"] is not None else "",
            "fullname": a["fullname"],
            "email": a["email"],
            "state": a["state"],
            "started": a["started"],
            "completed": a["completed"],
            "duration": a["duration"],
            "grade": f"{a['grade']}/{a['max_grade']}" if a["max_grade"] else a["grade"],
        })
    print_table(
        rows,
        columns=["attempt_id", "user_id", "fullname", "email", "state",
                 "started", "completed", "duration", "grade"],
        fmt=cast(OutputFmt, output),
    )


# ── results ───────────────────────────────────────────────────────────────────

@app.command("results")
def quiz_results(
        cmid: int = typer.Option(..., "--quiz", "-q", help="Quiz cmid (from `quizzes list`)."),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """Show the best graded attempt per student for one quiz.

    Each student appears once. The `attempts` column counts how many times
    they took the quiz; `best_grade` is the highest graded score.

    Examples:
      moodlectl quizzes results --quiz 978
      moodlectl quizzes results -q 978 --output csv > results.csv
    """
    client = MoodleClient.from_config(Config.load())
    try:
        results = quizzes_feature.get_results(client, Cmid(cmid))
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]No graded attempts found.[/yellow]")
        raise typer.Exit()

    rows: list[dict[str, str | int]] = []
    for r in results:
        rows.append({
            "user_id": r["user_id"] if r["user_id"] is not None else "",
            "fullname": r["fullname"],
            "email": r["email"],
            "attempts": r["attempts"],
            "best_grade": f"{r['best_grade']}/{r['max_grade']}" if r["max_grade"] else r["best_grade"],
        })
    print_table(
        rows,
        columns=["user_id", "fullname", "email", "attempts", "best_grade"],
        fmt=cast(OutputFmt, output),
    )


# ── info ──────────────────────────────────────────────────────────────────────

@app.command("info")
def quiz_info(
        cmid: int = typer.Option(..., "--quiz", "-q", help="Quiz cmid."),
):
    """Show summary stats for one quiz: attempts, state breakdown, grade range.

    Examples:
      moodlectl quizzes info --quiz 978
    """
    client = MoodleClient.from_config(Config.load())
    try:
        attempts = quizzes_feature.get_attempts(client, Cmid(cmid))
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if not attempts:
        console.print(f"[yellow]Quiz cmid={cmid}: no attempts.[/yellow]")
        raise typer.Exit()

    states: dict[str, int] = {}
    grades: list[float] = []
    for a in attempts:
        states[a["state"]] = states.get(a["state"], 0) + 1
        try:
            grades.append(float(a["grade"].replace(",", ".")))
        except ValueError:
            pass

    max_grade = attempts[0]["max_grade"]
    rows: list[dict[str, str]] = [
        {"field": "cmid", "value": str(cmid)},
        {"field": "total_attempts", "value": str(len(attempts))},
        {"field": "max_grade", "value": max_grade or "unknown"},
    ]
    for state, n in sorted(states.items()):
        rows.append({"field": f"state:{state}", "value": str(n)})
    if grades:
        rows.append({"field": "graded_attempts", "value": str(len(grades))})
        rows.append({"field": "min_grade", "value": f"{min(grades):.2f}"})
        rows.append({"field": "max_grade_seen", "value": f"{max(grades):.2f}"})
        rows.append({"field": "avg_grade", "value": f"{sum(grades)/len(grades):.2f}"})

    print_table(rows, columns=["field", "value"], fmt="table")


# ── delete ────────────────────────────────────────────────────────────────────

@app.command("delete")
def delete_quiz(
        cmid: int = typer.Option(..., "--quiz", "-q", help="Quiz cmid (from `quizzes list`)."),
        course: int = typer.Option(..., "--course", "-c", help="Course ID."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Delete a quiz activity.

    Removes the activity AND all its attempts and grades. This cannot be undone.
    The question bank is NOT deleted (use `questions delete-category` for that).

    Examples:
      moodlectl quizzes delete --quiz 1681 --course 83
      moodlectl quizzes delete -q 1681 -c 83 -y
    """
    client = MoodleClient.from_config(Config.load())

    if not yes:
        confirm = typer.confirm(
            f"Delete quiz cmid={cmid}? This will erase all attempts and grades.",
            default=False,
        )
        if not confirm:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit()

    try:
        content_feature.delete_module(client, CourseId(course), Cmid(cmid))
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Could not delete quiz:[/red] {exc}")
        raise typer.Exit(1)

    console.print(f"[green]Deleted quiz[/green] cmid={cmid}.")

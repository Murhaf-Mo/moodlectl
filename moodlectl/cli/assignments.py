from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import assignments as assignments_feature
from moodlectl.output.formatters import print_table

app = typer.Typer(help="Assignment commands")
console = Console()


def _load(course: tuple[int, ...]) -> tuple[MoodleClient, list[int], dict[int, dict]]:
    """Shared setup: load client, resolve course IDs, build course_map."""
    client = MoodleClient.from_config(Config.load())
    all_courses = client.get_courses()
    course_map = {c["id"]: c for c in all_courses}
    course_ids = list(course) if course else list(course_map.keys())
    return client, course_ids, course_map


@app.command("list")
def list_assignments(
    course: list[int] = typer.Option(
        None, "--course", "-c", help="Course ID (repeatable). Omit for all your courses."
    ),
    status: str = typer.Option("all", "--status", "-s", help="active, past, or all"),
    output: str = typer.Option("table", "--output", "-o", help="table, json, csv"),
):
    """List assignments across your courses.

    Examples:
      moodlectl assignments list
      moodlectl assignments list --status active
      moodlectl assignments list --course 568 --status past
    """
    client, course_ids, course_map = _load(tuple(course or []))

    assignments = assignments_feature.list_assignments(client, course_ids, status=status)

    if not assignments:
        console.print("[yellow]No assignments found.[/yellow]")
        raise typer.Exit()

    rows = []
    for a in assignments:
        course_info = course_map.get(a["course_id"], {})
        rows.append({
            "cmid": a["cmid"],
            "course": course_info.get("shortname", str(a["course_id"])),
            "assignment": a["name"],
            "status": a["status"],
            "due_date": a["due_text"] or "No due date",
            "submitted": a["submitted_count"],
        })

    print_table(rows, columns=["cmid", "course", "assignment", "status", "due_date", "submitted"], fmt=output)


@app.command("submissions")
def list_submissions(
    cmid: int = typer.Option(..., "--assignment", "-a", help="Assignment cmid (from `assignments list`)"),
    ungraded: bool = typer.Option(False, "--ungraded", help="Show only submissions that have not been graded yet"),
    output: str = typer.Option("table", "--output", "-o", help="table, json, csv"),
):
    """List who submitted an assignment and which files they uploaded — no downloads.

    Shows student name, email, submission status, grading status, and filenames.
    Use --ungraded to filter to submissions that still need grading.
    Use --output csv to export the list.

    Examples:
      moodlectl assignments submissions --assignment 18002
      moodlectl assignments submissions --assignment 18002 --ungraded
      moodlectl assignments submissions --assignment 18002 --output csv > submitted.csv
    """
    client = MoodleClient.from_config(Config.load())

    try:
        submissions = client.get_assignment_submissions(cmid)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if ungraded:
        submissions = [s for s in submissions if assignments_feature.is_ungraded(s)]

    if not submissions:
        msg = "[yellow]No ungraded submissions found.[/yellow]" if ungraded else "[yellow]No submissions found.[/yellow]"
        console.print(msg)
        raise typer.Exit()

    rows = []
    for s in submissions:
        filenames = ", ".join(f["filename"] for f in s["files"]) if s["files"] else "—"
        rows.append({
            "user_id": s["user_id"],
            "fullname": s["fullname"],
            "email": s["email"],
            "status": s["status"],
            "grading_status": s.get("grading_status", ""),
            "files": filenames,
        })

    print_table(rows, columns=["user_id", "fullname", "email", "status", "grading_status", "files"], fmt=output)


@app.command("missing")
def missing_submissions(
    cmid: int = typer.Option(..., "--assignment", "-a", help="Assignment cmid (from `assignments list`)"),
    course: int = typer.Option(..., "--course", "-c", help="Course ID (from `courses list`)"),
    output: str = typer.Option("table", "--output", "-o", help="table, json, csv"),
):
    """Show students who have NOT submitted for an assignment.

    Compares enrolled students against submitted ones and lists the difference,
    along with each student's last access time so you can gauge activity.

    Examples:
      moodlectl assignments missing --assignment 18002 --course 568
      moodlectl assignments missing --assignment 18002 --course 568 --output csv > missing.csv
    """
    client = MoodleClient.from_config(Config.load())

    try:
        missing = assignments_feature.get_missing_submissions(client, cmid=cmid, course_id=course)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if not missing:
        console.print("[green]All students have submitted.[/green]")
        raise typer.Exit()

    console.print(f"[yellow]{len(missing)} student(s) have not submitted.[/yellow]\n")
    print_table(missing, columns=["user_id", "fullname", "email", "lastaccess"], fmt=output)


@app.command("ungraded-all")
def ungraded_all_submissions(
    course: list[int] = typer.Option(
        None, "--course", "-c", help="Course ID (repeatable). Omit for all your courses."
    ),
    status: str = typer.Option("all", "--status", "-s", help="active, past, or all"),
    output: str = typer.Option("table", "--output", "-o", help="table, json, csv"),
):
    """List all submitted assignments that have not been graded yet, across all courses.

    Use --status to narrow to past or active assignments.

    Examples:
      moodlectl assignments ungraded-all
      moodlectl assignments ungraded-all --status past
      moodlectl assignments ungraded-all --course 590
      moodlectl assignments ungraded-all --output csv > ungraded.csv
    """
    client, course_ids, course_map = _load(tuple(course or []))

    ungraded = assignments_feature.get_all_ungraded_submissions(
        client, course_ids, course_map=course_map, status=status
    )

    if not ungraded:
        console.print("[green]All submissions are graded.[/green]")
        raise typer.Exit()

    console.print(f"\n[yellow]{len(ungraded)} ungraded submission(s) found.[/yellow]\n")
    print_table(
        ungraded,
        columns=["course", "assignment", "assignment_status", "due_date", "user_id", "fullname", "email", "grading_status", "files"],
        fmt=output,
    )


@app.command("missing-all")
def missing_all_submissions(
    course: list[int] = typer.Option(
        None, "--course", "-c", help="Course ID (repeatable). Omit for all your courses."
    ),
    status: str = typer.Option("all", "--status", "-s", help="active, past, or all"),
    output: str = typer.Option("table", "--output", "-o", help="table, json, csv"),
):
    """Show all students who have NOT submitted across all courses and assignments.

    Use --status to narrow to past (already due) or active (not due yet) assignments.

    Examples:
      moodlectl assignments missing-all
      moodlectl assignments missing-all --status past
      moodlectl assignments missing-all --course 590 --status active
      moodlectl assignments missing-all --output csv > missing.csv
    """
    client, course_ids, course_map = _load(tuple(course or []))

    missing = assignments_feature.get_all_missing_submissions(
        client, course_ids, course_map=course_map, status=status
    )

    if not missing:
        console.print("[green]No missing submissions found.[/green]")
        raise typer.Exit()

    console.print(f"\n[yellow]{len(missing)} missing submission(s) found.[/yellow]\n")
    print_table(
        missing,
        columns=["course", "assignment", "assignment_status", "due_date", "user_id", "fullname", "email", "lastaccess"],
        fmt=output,
    )


@app.command("info")
def assignment_info(
    cmid: int = typer.Option(..., "--assignment", "-a", help="Assignment cmid (from `assignments list`)"),
):
    """Show full details for an assignment: cmid, grade scale, due date, submission count.

    Fetches the grade max by reading the grading form from the first submission.

    Examples:
      moodlectl assignments info --assignment 18002
    """
    client = MoodleClient.from_config(Config.load())

    # Resolve internal IDs
    try:
        assignment_id, context_id = client.get_assignment_internal_id(cmid)
    except Exception as exc:
        console.print(f"[red]Could not resolve assignment IDs:[/red] {exc}")
        raise typer.Exit(1)

    # Get grade_max from the grading fragment using the first submitter
    grade_max = None
    try:
        submissions = client.get_assignment_submissions(cmid)
        if submissions:
            first_user_id = submissions[0]["user_id"]
            fragment = client.get_grade_form_fragment(context_id, first_user_id)
            grade_max = fragment.get("__grade_max__") or None
    except Exception:
        pass  # grade_max stays None if we can't fetch it

    # Find assignment metadata from courses
    all_courses = client.get_courses()
    course_map = {c["id"]: c for c in all_courses}
    meta = None
    for cid in course_map:
        try:
            for a in client.get_course_assignments(cid):
                if a["cmid"] == cmid:
                    meta = {**a, "course_id": cid}
                    break
        except Exception:
            continue
        if meta:
            break

    course_info = course_map.get(meta["course_id"], {}) if meta else {}

    rows = [{
        "field": "cmid",
        "value": str(cmid),
    }, {
        "field": "assignment_id",
        "value": str(assignment_id),
    }, {
        "field": "context_id",
        "value": str(context_id),
    }, {
        "field": "course",
        "value": course_info.get("shortname", "unknown"),
    }, {
        "field": "name",
        "value": meta["name"] if meta else "unknown",
    }, {
        "field": "due_date",
        "value": (meta["due_text"] or "No due date") if meta else "unknown",
    }, {
        "field": "submitted",
        "value": str(meta["submitted_count"]) if meta else "unknown",
    }, {
        "field": "grade_max",
        "value": str(grade_max) if grade_max is not None else "unknown",
    }]

    print_table(rows, columns=["field", "value"], fmt="table")


@app.command("download")
def download_submissions(
    course: list[int] = typer.Option(
        None, "--course", "-c", help="Course ID (repeatable). Omit for all your courses."
    ),
    status: str = typer.Option("all", "--status", "-s", help="active, past, or all"),
    out: Path = typer.Option(Path("assignments"), "--out", help="Output directory"),
    ungraded: bool = typer.Option(False, "--ungraded", help="Download only submissions that have not been graded yet"),
):
    """Download submitted assignment files, organised by course and status.

    Output layout:
      {out}/{course}/{active|past}/{assignment}/{student_name_id}/file.pdf

    Use --ungraded to only download files from students who still need grading.

    Examples:
      moodlectl assignments download
      moodlectl assignments download --course 568 --status active
      moodlectl assignments download --course 568 --status past --out ./archive
      moodlectl assignments download --ungraded
    """
    client, course_ids, course_map = _load(tuple(course or []))

    assignments_feature.download_submissions(
        client,
        course_ids,
        course_map=course_map,
        status=status,
        out_dir=out,
        ungraded_only=ungraded,
    )

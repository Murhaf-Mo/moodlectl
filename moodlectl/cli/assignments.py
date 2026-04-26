from __future__ import annotations

from pathlib import Path
from typing import Optional, cast

import typer
from rich.console import Console

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import assignments as assignments_feature
from moodlectl.features import content as content_feature
from moodlectl.output.formatters import print_table
from moodlectl.types import AssignmentStatus, Cmid, CourseId, CourseMap, OutputFmt

app = typer.Typer(help="Assignment commands — list, submissions, grading status, downloads, and reminders.")
console = Console()


def _load(course: tuple[int, ...]) -> tuple[MoodleClient, list[CourseId], CourseMap]:
    """Shared setup: load client, resolve course IDs, build course_map.

    If course is empty, all enrolled courses are used.
    """
    client = MoodleClient.from_config(Config.load())
    all_courses = client.get_courses()
    course_map: CourseMap = {c["id"]: c for c in all_courses}
    course_ids = [CourseId(c) for c in course] if course else list(course_map.keys())
    return client, course_ids, course_map


# ── list ──────────────────────────────────────────────────────────────────────

@app.command("list")
def list_assignments(
        course: list[int] = typer.Option(
            None, "--course", "-c", help="Course ID (repeatable). Omit for all your courses."
        ),
        status: str = typer.Option("all", "--status", "-s", help="Filter by status: active, past, or all."),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """List assignments across your courses.

    STATUS values:
      active — due date is in the future, or no due date set
      past   — due date has already passed
      all    — no filtering (default)

    The cmid column is the ID used by all other assignment and grading commands.

    Examples:
      moodlectl assignments list
      moodlectl assignments list --status active
      moodlectl assignments list --course 568 --status past
      moodlectl assignments list --output csv > assignments.csv
    """
    client, course_ids, course_map = _load(tuple(course or []))

    assignments = assignments_feature.list_assignments(client, course_ids, status=cast(AssignmentStatus, status))

    if not assignments:
        console.print("[yellow]No assignments found.[/yellow]")
        raise typer.Exit()

    rows: list[dict[str, str | int]] = []
    for a in assignments:
        course_info = course_map.get(a["course_id"])
        rows.append({
            "cmid": a["cmid"],
            "course": course_info["shortname"] if course_info is not None else str(a["course_id"]),
            "assignment": a["name"],
            "status": a["status"],
            "due_date": a["due_text"] or "No due date",
            "submitted": a["submitted_count"],
        })

    print_table(rows, columns=["cmid", "course", "assignment", "status", "due_date", "submitted"],
                fmt=cast(OutputFmt, output))


# ── info ──────────────────────────────────────────────────────────────────────

@app.command("info")
def assignment_info(
        cmid: int = typer.Option(..., "--assignment", "-a", help="Assignment cmid (from `assignments list`)."),
):
    """Show full details for a single assignment.

    Displays cmid, internal IDs, course, name, due date, submission count,
    and grade scale. The grade scale is read from the grading form of the
    first submitted student.

    Examples:
      moodlectl assignments info --assignment 18002
    """
    client = MoodleClient.from_config(Config.load())

    try:
        assignment_id, context_id = client.get_assignment_internal_id(Cmid(cmid))
    except Exception as exc:
        console.print(f"[red]Could not resolve assignment IDs:[/red] {exc}")
        raise typer.Exit(1)

    # Read grade_max from the grading form of the first submitter
    grade_max = None
    try:
        submissions = client.get_assignment_submissions(Cmid(cmid))
        if submissions:
            first_user_id = submissions[0]["user_id"]
            fragment = client.get_grade_form_fragment(context_id, first_user_id)
            grade_max = fragment.get("__grade_max__") or None
    except Exception:
        pass  # grade_max stays None if no submissions or fragment unavailable

    # Locate assignment metadata by scanning all courses
    from moodlectl.types import AssignmentMeta
    all_courses = client.get_courses()
    course_map = {c["id"]: c for c in all_courses}
    meta: AssignmentMeta | None = None
    meta_course_id: CourseId | None = None
    for cid in course_map:
        try:
            for a in client.get_course_assignments(cid):
                if a["cmid"] == cmid:
                    meta = a
                    meta_course_id = cid
                    break
        except Exception:
            continue
        if meta:
            break

    course_info = course_map.get(meta_course_id) if meta_course_id is not None else None

    rows: list[dict[str, str]] = [
        {"field": "cmid", "value": str(cmid)},
        {"field": "assignment_id", "value": str(assignment_id)},
        {"field": "context_id", "value": str(context_id)},
        {"field": "course", "value": course_info["shortname"] if course_info is not None else "unknown"},
        {"field": "name", "value": meta["name"] if meta else "unknown"},
        {"field": "due_date", "value": (meta["due_text"] or "No due date") if meta else "unknown"},
        {"field": "submitted", "value": str(meta["submitted_count"]) if meta else "unknown"},
        {"field": "grade_max", "value": str(grade_max) if grade_max is not None else "unknown"},
    ]

    print_table(rows, columns=["field", "value"], fmt="table")


# ── submissions ───────────────────────────────────────────────────────────────

@app.command("submissions")
def list_submissions(
        cmid: int = typer.Option(..., "--assignment", "-a", help="Assignment cmid (from `assignments list`)."),
        ungraded: bool = typer.Option(False, "--ungraded", help="Show only submissions that have not been graded yet."),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """List who submitted an assignment and which files they uploaded.

    Shows student name, email, submission status, grading status, and filenames.
    Use --ungraded to filter to submissions that still need a grade.
    Use `grading next --assignment` for an interactive grading session.

    Examples:
      moodlectl assignments submissions --assignment 18002
      moodlectl assignments submissions --assignment 18002 --ungraded
      moodlectl assignments submissions --assignment 18002 --output csv > submitted.csv
    """
    client = MoodleClient.from_config(Config.load())

    try:
        submissions = client.get_assignment_submissions(Cmid(cmid))
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if ungraded:
        submissions = [s for s in submissions if assignments_feature.is_ungraded(s)]

    if not submissions:
        msg = "[yellow]No ungraded submissions found.[/yellow]" if ungraded else "[yellow]No submissions found.[/yellow]"
        console.print(msg)
        raise typer.Exit()

    rows: list[dict[str, str | int]] = []
    for s in submissions:
        filenames = ", ".join(f["filename"] for f in s["files"]) if s["files"] else "—"
        rows.append({
            "user_id": s["user_id"],
            "fullname": s["fullname"],
            "email": s["email"],
            "status": s["status"],
            "grading_status": s["grading_status"],
            "files": filenames,
        })

    print_table(rows, columns=["user_id", "fullname", "email", "status", "grading_status", "files"],
                fmt=cast(OutputFmt, output))


# ── missing ───────────────────────────────────────────────────────────────────

@app.command("missing")
def missing_submissions(
        cmid: Optional[int] = typer.Option(
            None, "--assignment", "-a",
            help="Assignment cmid (from `assignments list`). Requires --course. Omit to scan all assignments."
        ),
        course: list[int] = typer.Option(
            None, "--course", "-c",
            help="Course ID. Required with --assignment. Repeatable when scanning all assignments."
        ),
        status: str = typer.Option(
            "all", "--status", "-s",
            help="Filter by assignment status: active, past, or all. Only used when scanning all assignments."
        ),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """Show students who have NOT submitted.

    With --assignment and --course: checks one assignment.
    Without --assignment: scans all assignments across all courses (or selected --course IDs).

    The lastaccess column shows when each student last logged in, helping you
    gauge whether they are likely to submit or are unreachable.

    Examples:
      moodlectl assignments missing --assignment 18002 --course 568
      moodlectl assignments missing
      moodlectl assignments missing --status past
      moodlectl assignments missing --course 568 --status active
      moodlectl assignments missing --output csv > missing.csv
    """
    client = MoodleClient.from_config(Config.load())

    # Single-assignment path: --assignment and --course both provided
    if cmid is not None:
        if not course:
            console.print("[red]--course is required when --assignment is specified.[/red]")
            raise typer.Exit(1)
        course_id = CourseId(course[0])
        try:
            missing = assignments_feature.get_missing_submissions(client, cmid=Cmid(cmid), course_id=course_id)
        except RuntimeError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1)

        if not missing:
            console.print("[green]All students have submitted.[/green]")
            raise typer.Exit()

        console.print(f"[yellow]{len(missing)} student(s) have not submitted.[/yellow]\n")
        print_table(missing, columns=["user_id", "fullname", "email", "lastaccess"], fmt=cast(OutputFmt, output))
        return

    # Bulk path: scan all assignments across all (or selected) courses
    all_courses = client.get_courses()
    course_map: CourseMap = {c["id"]: c for c in all_courses}
    course_ids = [CourseId(c) for c in course] if course else list(course_map.keys())

    missing = assignments_feature.get_all_missing_submissions(
        client, course_ids, course_map=course_map, status=cast(AssignmentStatus, status)
    )

    if not missing:
        console.print("[green]No missing submissions found.[/green]")
        raise typer.Exit()

    console.print(f"\n[yellow]{len(missing)} missing submission(s) found.[/yellow]\n")
    print_table(
        missing,
        columns=["course", "assignment", "assignment_status", "due_date", "user_id", "fullname", "email", "lastaccess"],
        fmt=cast(OutputFmt, output),
    )


# ── ungraded ──────────────────────────────────────────────────────────────────

@app.command("ungraded")
def ungraded_submissions(
        course: list[int] = typer.Option(
            None, "--course", "-c", help="Course ID (repeatable). Omit for all your courses."
        ),
        status: str = typer.Option("all", "--status", "-s", help="Filter by assignment status: active, past, or all."),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """List all submitted assignments that have not been graded yet, across all courses.

    Use `grading next --assignment` to interactively grade through the list for
    one assignment at a time, or `grading batch` to grade from a CSV file.

    Examples:
      moodlectl assignments ungraded
      moodlectl assignments ungraded --status past
      moodlectl assignments ungraded --course 590
      moodlectl assignments ungraded --output csv > ungraded.csv
    """
    client, course_ids, course_map = _load(tuple(course or []))

    ungraded = assignments_feature.get_all_ungraded_submissions(
        client, course_ids, course_map=course_map, status=cast(AssignmentStatus, status)
    )

    if not ungraded:
        console.print("[green]All submissions are graded.[/green]")
        raise typer.Exit()

    console.print(f"\n[yellow]{len(ungraded)} ungraded submission(s) found.[/yellow]\n")
    print_table(
        ungraded,
        columns=["course", "assignment", "assignment_status", "due_date", "user_id", "fullname", "email",
                 "grading_status", "files"],
        fmt=cast(OutputFmt, output),
    )


# ── remind ────────────────────────────────────────────────────────────────────

@app.command("remind")
def remind_missing(
        cmid: int = typer.Option(..., "--assignment", "-a", help="Assignment cmid (from `assignments list`)."),
        course: int = typer.Option(..., "--course", "-c", help="Course ID (from `courses list`)."),
        text: str = typer.Option(..., "--text", "-t", help="Message text to send to each missing student."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show who would be messaged without sending anything."),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """Send a Moodle message to every student who hasn't submitted an assignment.

    Use --dry-run first to preview who will be messaged before sending.

    Examples:
      moodlectl assignments remind --assignment 18002 --course 568 --text "Reminder: your assignment is due Friday."
      moodlectl assignments remind --assignment 18002 --course 568 --text "..." --dry-run
    """
    client = MoodleClient.from_config(Config.load())

    try:
        missing = assignments_feature.get_missing_submissions(client, cmid=Cmid(cmid), course_id=CourseId(course))
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if not missing:
        console.print("[green]No missing submissions — nobody to remind.[/green]")
        raise typer.Exit()

    if dry_run:
        console.print(f"[dim](dry run) Would message {len(missing)} student(s):[/dim]\n")
        print_table(missing, columns=["user_id", "fullname", "email"], fmt=cast(OutputFmt, output))
        return

    results = assignments_feature.remind_missing_students(client, cmid=Cmid(cmid), course_id=CourseId(course),
                                                          message_text=text)
    sent = sum(1 for r in results if r.get("sent"))
    console.print(f"\n[green]{sent}[/green] of {len(results)} message(s) sent.\n")
    print_table(results, columns=["user_id", "fullname", "email", "sent"], fmt=cast(OutputFmt, output))


# ── remind-all ────────────────────────────────────────────────────────────────

@app.command("remind-all")
def remind_all_missing(
        course: list[int] = typer.Option(
            None, "--course", "-c", help="Course ID (repeatable). Omit for all your courses."
        ),
        status: str = typer.Option("all", "--status", "-s", help="Filter by assignment status: active, past, or all."),
        text: str = typer.Option(..., "--text", "-t", help="Message text to send to each missing student."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show who would be messaged without sending anything."),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """Send reminders to all students missing submissions, across all courses.

    Each student gets one message per assignment they haven't submitted.
    Use --dry-run first to preview the full list before sending.

    Examples:
      moodlectl assignments remind-all --text "Please submit your pending assignments."
      moodlectl assignments remind-all --status active --text "Deadline approaching!" --dry-run
      moodlectl assignments remind-all --course 568 --text "..." --output csv > sent.csv
    """
    client, course_ids, course_map = _load(tuple(course or []))

    if dry_run:
        # Show missing list without sending
        missing = assignments_feature.get_all_missing_submissions(
            client, course_ids, course_map=course_map, status=cast(AssignmentStatus, status)
        )
        if not missing:
            console.print("[green]No missing submissions — nobody to remind.[/green]")
            raise typer.Exit()
        console.print(f"[dim](dry run) Would message {len(missing)} student/assignment pair(s):[/dim]\n")
        print_table(missing, columns=["course", "assignment", "user_id", "fullname", "email"],
                    fmt=cast(OutputFmt, output))
        return

    results = assignments_feature.remind_all_missing_students(
        client, course_ids, course_map=course_map, message_text=text, status=cast(AssignmentStatus, status)
    )

    if not results:
        console.print("[green]No missing submissions — nobody to remind.[/green]")
        raise typer.Exit()

    sent = sum(1 for r in results if r.get("sent"))
    console.print(f"\n[green]{sent}[/green] of {len(results)} message(s) sent.\n")
    print_table(results, columns=["course", "assignment", "user_id", "fullname", "sent"], fmt=cast(OutputFmt, output))


# ── due-soon ──────────────────────────────────────────────────────────────────

@app.command("due-soon")
def due_soon(
        course: list[int] = typer.Option(
            None, "--course", "-c", help="Course ID (repeatable). Omit for all your courses."
        ),
        days: int = typer.Option(7, "--days", "-d", help="Number of days to look ahead (default: 7)."),
        output: str = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv."),
):
    """Show active assignments with a due date in the next N days.

    Sorted by most urgent first (fewest days remaining). Assignments with
    no due date are excluded. Use this for a quick morning check of upcoming deadlines.

    Examples:
      moodlectl assignments due-soon
      moodlectl assignments due-soon --days 3
      moodlectl assignments due-soon --course 568 --days 14
    """
    client, course_ids, course_map = _load(tuple(course or []))

    due = assignments_feature.get_due_soon(client, course_ids, course_map, days=days)

    if not due:
        console.print(f"[green]No assignments due in the next {days} day(s).[/green]")
        raise typer.Exit()

    console.print(f"\n[bold yellow]{len(due)} assignment(s) due in the next {days} day(s):[/bold yellow]\n")
    print_table(due, columns=["course", "cmid", "assignment", "due_date", "submitted", "days_left"],
                fmt=cast(OutputFmt, output))


# ── download ──────────────────────────────────────────────────────────────────

@app.command("download")
def download_submissions(
        course: list[int] = typer.Option(
            None, "--course", "-c", help="Course ID (repeatable). Omit for all your courses."
        ),
        status: str = typer.Option("all", "--status", "-s", help="Filter by assignment status: active, past, or all."),
        out: Path = typer.Option(Path("assignments"), "--out", help="Output directory (default: ./assignments)."),
        ungraded: bool = typer.Option(False, "--ungraded",
                                      help="Download only submissions that have not been graded yet."),
        user: list[int] = typer.Option(
            None, "--user", "-u",
            help="User ID (repeatable). Only download files submitted by these users."
        ),
):
    """Download submitted assignment files, organised by course and status.

    Output layout:
      {out}/{course_short}/{active|past}/{assignment}/{student_name_id}/file.pdf

    Instructor-attached brief files are saved to a _brief/ subfolder.
    Use --ungraded to only download files from students who still need grading.
    Use --user to restrict to specific students (e.g. for plagiarism comparisons).

    Examples:
      moodlectl assignments download
      moodlectl assignments download --course 568 --status active
      moodlectl assignments download --course 568 --status past --out ./archive
      moodlectl assignments download --ungraded
      moodlectl assignments download --course 581 --user 1542 --user 1481
    """
    client, course_ids, course_map = _load(tuple(course or []))

    assignments_feature.download_submissions(
        client,
        course_ids,
        course_map=course_map,
        status=cast(AssignmentStatus, status),
        out_dir=out,
        ungraded_only=ungraded,
        user_ids=list(user) if user else None,
    )


# ── create ───────────────────────────────────────────────────────────────────-

_DEFAULT_FILETYPES = ".pdf,.docx,.doc,.zip"


@app.command("create")
def create_assignment(
        course: int = typer.Option(..., "--course", "-c", help="Course ID."),
        section: int = typer.Option(..., "--section", "-s", help="Section number (0-indexed)."),
        name: str = typer.Option(..., "--name", "-n", help="Assignment name."),
        description: Optional[str] = typer.Option(None, "--description", help="Assignment description (HTML or plain text)."),
        due: Optional[str] = typer.Option(None, "--due", help="Due date, ISO 8601 (e.g. 2026-05-04T23:59)."),
        cutoff: Optional[str] = typer.Option(None, "--cutoff", help="Hard cut-off after which submissions are blocked."),
        available_from: Optional[str] = typer.Option(None, "--available-from", help="Date submissions open."),
        max_grade: int = typer.Option(100, "--max-grade", help="Maximum grade (default: 100)."),
        submission_types: str = typer.Option(
            "file", "--submission-types",
            help="Comma-separated: file, online_text. Default: file.",
        ),
        max_files: int = typer.Option(1, "--max-files", help="Max files for file submission (default: 1)."),
        filetypes: str = typer.Option(
            _DEFAULT_FILETYPES, "--filetypes",
            help=f"Accepted file extensions, comma-separated (default: {_DEFAULT_FILETYPES}).",
        ),
        word_limit: Optional[int] = typer.Option(None, "--word-limit", help="Word limit for online_text (omit for none)."),
        max_attempts: Optional[int] = typer.Option(None, "--max-attempts", help="Max attempts (-1 = unlimited)."),
        attempts_method: str = typer.Option(
            "none", "--attempts-method",
            help="When attempts reopen: none|manual|untilpass (default: none).",
        ),
        blind_marking: bool = typer.Option(False, "--blind-marking", help="Hide student identities from graders."),
        team_submission: bool = typer.Option(False, "--team-submission", help="Group/team submissions."),
        feedback_comments: bool = typer.Option(True, "--feedback-comments/--no-feedback-comments",
                                               help="Enable feedback comments (default: on)."),
        feedback_file: bool = typer.Option(False, "--feedback-file", help="Allow grader to upload feedback files."),
        visible: bool = typer.Option(False, "--visible/--hidden", help="Visibility on course page (default: hidden)."),
):
    """Create an assignment activity in a course section.

    Creates the assignment in hidden mode by default — toggle with --visible
    once the brief is ready for students.

    Examples:
      moodlectl assignments create --course 581 --section 11 \\
          --name "Assignment 4 — SQL Filtering" \\
          --due 2026-05-04T23:59 --max-grade 20 --filetypes .pdf

      moodlectl assignments create -c 581 -s 11 -n "Quiz makeup" \\
          --submission-types file,online_text --word-limit 500
    """
    client = MoodleClient.from_config(Config.load())

    types_set = {t.strip() for t in submission_types.split(",") if t.strip()}
    unknown = types_set - {"file", "online_text"}
    if unknown:
        console.print(f"[red]Unknown submission type(s): {', '.join(unknown)}[/red]")
        raise typer.Exit(1)

    if attempts_method not in {"none", "manual", "untilpass"}:
        console.print("[red]--attempts-method must be one of: none, manual, untilpass[/red]")
        raise typer.Exit(1)

    settings: dict[str, object] = {
        "visible": 1 if visible else 0,
        "grade_type": "point",
        "max_grade": max_grade,
        "submission_type_file": 1 if "file" in types_set else 0,
        "submission_type_online_text": 1 if "online_text" in types_set else 0,
        "feedback_comments": 1 if feedback_comments else 0,
        "feedback_file": 1 if feedback_file else 0,
        "anonymous_submissions": 1 if blind_marking else 0,
        "team_submission": 1 if team_submission else 0,
        "submission_attempts": attempts_method,
    }
    if description:
        settings["description"] = description
    if due:
        settings["due_date"] = due.replace("T", " ")
    if cutoff:
        settings["cutoff_date"] = cutoff.replace("T", " ")
    if available_from:
        settings["available_from"] = available_from.replace("T", " ")
    if "file" in types_set:
        settings["max_files"] = max_files
        settings["accepted_filetypes"] = filetypes
    if "online_text" in types_set and word_limit is not None:
        settings["word_limit_enabled"] = 1
        settings["word_limit"] = word_limit
    if max_attempts is not None:
        settings["max_attempts"] = max_attempts

    try:
        cmid = content_feature.create_module(
            client, CourseId(course), section, "assign", name, settings=settings,
        )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Could not create assignment:[/red] {exc}")
        raise typer.Exit(1)

    visibility = "visible" if visible else "hidden"
    console.print(
        f"[green]Created assignment[/green] [bold]{name}[/bold] "
        f"(cmid={cmid}, {visibility}) in course {course} section {section}."
    )


# ── delete ───────────────────────────────────────────────────────────────────-

@app.command("delete")
def delete_assignment(
        cmid: int = typer.Option(..., "--assignment", "-a", help="Assignment cmid (from `assignments list`)."),
        course: int = typer.Option(..., "--course", "-c", help="Course ID."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
):
    """Delete an assignment activity.

    Removes the activity AND all its submissions, grades, and feedback.
    This cannot be undone — Moodle does not soft-delete `mod_assign`.

    Examples:
      moodlectl assignments delete --assignment 18002 --course 581
      moodlectl assignments delete -a 18002 -c 581 -y
    """
    client = MoodleClient.from_config(Config.load())

    if not yes:
        confirm = typer.confirm(
            f"Delete assignment cmid={cmid}? This will erase all submissions and grades.",
            default=False,
        )
        if not confirm:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit()

    try:
        content_feature.delete_module(client, CourseId(course), Cmid(cmid))
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Could not delete assignment:[/red] {exc}")
        raise typer.Exit(1)

    console.print(f"[green]Deleted assignment[/green] cmid={cmid}.")

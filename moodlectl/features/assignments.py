from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from moodlectl.types import (
    AssignmentListing,
    AssignmentStatus,
    BulkReminderResult,
    Cmid,
    CourseId,
    CourseMap,
    DownloadResult,
    DueSoon,
    MissingResult,
    MissingStudent,
    MoodleClientProtocol,
    Participant,
    ReminderResult,
    Submission,
    UngradedResult,
)

# Moodle displays due dates in this format: "Thursday, 26 March 2026, 11:59 PM"
_DUE_DATE_FMT = "%A, %d %B %Y, %I:%M %p"


def _parse_due(due_text: str) -> datetime | None:
    """Parse Moodle due date text to a datetime, or None if unparseable."""
    try:
        return datetime.strptime(due_text.strip(), _DUE_DATE_FMT)
    except ValueError:
        return None


def _safe_name(name: str) -> str:
    """Strip characters illegal in directory/file names, limit length to 80 chars."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name[:80] or "unnamed"


def list_assignments(
        client: MoodleClientProtocol,
        course_ids: list[CourseId],
        status: AssignmentStatus = "all",
) -> list[AssignmentListing]:
    """Return assignments across courses filtered by status.

    status values:
      'active' — future due date or no due date
      'past'   — due date has passed
      'all'    — no filtering

    Each result dict includes: course_id, cmid, name, due_text, due_dt,
    submitted_count, status.
    """
    now = datetime.now()
    results: list[AssignmentListing] = []

    for cid in course_ids:
        try:
            course_assignments = client.get_course_assignments(cid)
        except Exception:
            # Don't abort the whole run if one course is inaccessible
            continue

        for assign in course_assignments:
            due_dt = _parse_due(assign["due_text"])
            assign_status: Literal["active", "past"]
            if due_dt is None:
                assign_status = "active"  # no parseable due date → treat as active
            elif due_dt > now:
                assign_status = "active"
            else:
                assign_status = "past"

            if status != "all" and assign_status != status:
                continue

            results.append({
                "course_id": cid,
                "cmid": assign["cmid"],
                "name": assign["name"],
                "due_text": assign["due_text"],
                "due_dt": due_dt,
                "submitted_count": assign["submitted_count"],
                "status": assign_status,
            })

    return results


def get_missing_submissions(
        client: MoodleClientProtocol,
        cmid: Cmid,
        course_id: CourseId,
) -> list[MissingStudent]:
    """Return students enrolled as students who have not submitted to cmid.

    Each result: {user_id, fullname, email, lastaccess}
    """
    submissions = client.get_assignment_submissions(cmid)
    submitted_ids = {s["user_id"] for s in submissions}

    participants = client.get_course_participants(course_id)
    missing: list[MissingStudent] = []
    for p in participants:
        roles = p.get("roles", "")
        if "student" not in roles.lower():
            continue
        if p["id"] not in submitted_ids:
            missing.append({
                "user_id": p["id"],
                "fullname": p["fullname"],
                "email": p["email"],
                "lastaccess": p.get("lastaccess", ""),
            })
    return missing


def get_all_missing_submissions(
        client: MoodleClientProtocol,
        course_ids: list[CourseId],
        course_map: CourseMap,
        status: AssignmentStatus = "all",
) -> list[MissingResult]:
    """Return all students who have not submitted across all given courses/assignments.

    Participants are cached per course to avoid redundant requests.
    Each result: {course, assignment, assignment_status, due_date, user_id, fullname,
                  email, lastaccess}
    """
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn

    console = Console()
    assignments = list_assignments(client, course_ids, status=status)

    if not assignments:
        return []

    participants_cache: dict[int, list[Participant]] = {}
    results: list[MissingResult] = []

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Scanning…", total=len(assignments))

        for assign in assignments:
            cid = assign["course_id"]
            cmid = assign["cmid"]
            course_info = course_map.get(cid)
            course_short = course_info["shortname"] if course_info is not None else str(cid)

            progress.update(task, description=f"[cyan]{assign['name'][:50]}[/cyan]")

            try:
                submissions = client.get_assignment_submissions(cmid)
            except Exception as exc:
                console.print(f"[yellow]  Warning: {assign['name']}: {exc}[/yellow]")
                progress.advance(task)
                continue

            submitted_ids = {s["user_id"] for s in submissions}

            if cid not in participants_cache:
                try:
                    participants_cache[cid] = client.get_course_participants(cid)
                except Exception as exc:
                    console.print(f"[yellow]  Warning: could not fetch participants for course {cid}: {exc}[/yellow]")
                    participants_cache[cid] = []

            for p in participants_cache[cid]:
                if "student" not in p.get("roles", "").lower():
                    continue
                if p["id"] not in submitted_ids:
                    results.append({
                        "course": course_short,
                        "assignment": assign["name"],
                        "assignment_status": assign["status"],
                        "due_date": assign["due_text"] or "No due date",
                        "user_id": p["id"],
                        "fullname": p["fullname"],
                        "email": p["email"],
                        "lastaccess": p.get("lastaccess", ""),
                    })

            progress.advance(task)

    return results


def is_ungraded(submission: Submission) -> bool:
    """Return True if the submission has not been graded yet.

    Moodle shows the actual grade value (e.g. "Grade5.00 / 5.00") when graded.
    Ungraded submissions show "-", empty string, or "Not graded" — no digits.
    """
    gs = str(submission.get("grading_status", ""))
    return not bool(re.search(r"\d", gs))


def get_all_ungraded_submissions(
        client: MoodleClientProtocol,
        course_ids: list[CourseId],
        course_map: CourseMap,
        status: AssignmentStatus = "all",
) -> list[UngradedResult]:
    """Return all submitted-but-ungraded entries across all given courses/assignments.

    Skips assignments with zero submissions to avoid unnecessary requests.
    Each result: {course, assignment, assignment_status, due_date, user_id, fullname,
                  email, grading_status, files}
    """
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn

    console = Console()
    assignments = list_assignments(client, course_ids, status=status)

    if not assignments:
        return []

    results: list[UngradedResult] = []

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Scanning…", total=len(assignments))

        for assign in assignments:
            cid = assign["course_id"]
            course_info = course_map.get(cid)
            course_short = course_info["shortname"] if course_info is not None else str(cid)

            progress.update(task, description=f"[cyan]{assign['name'][:50]}[/cyan]")

            # Skip assignments with no submissions to save a request
            if assign["submitted_count"] == 0:
                progress.advance(task)
                continue

            try:
                submissions = client.get_assignment_submissions(assign["cmid"])
            except Exception as exc:
                console.print(f"[yellow]  Warning: {assign['name']}: {exc}[/yellow]")
                progress.advance(task)
                continue

            for sub in submissions:
                if is_ungraded(sub):
                    filenames = ", ".join(f["filename"] for f in sub["files"]) if sub["files"] else "—"
                    results.append({
                        "course": course_short,
                        "assignment": assign["name"],
                        "assignment_status": assign["status"],
                        "due_date": assign["due_text"] or "No due date",
                        "user_id": sub["user_id"],
                        "fullname": sub["fullname"],
                        "email": sub["email"],
                        "grading_status": sub.get("grading_status", ""),
                        "files": filenames,
                    })

            progress.advance(task)

    return results


def remind_missing_students(
        client: MoodleClientProtocol,
        cmid: Cmid,
        course_id: CourseId,
        message_text: str,
) -> list[ReminderResult]:
    """Send a Moodle message to every student who has not submitted cmid.

    Returns list of {user_id, fullname, email, lastaccess, sent} — sent=True means the
    message was delivered without error.
    """
    missing = get_missing_submissions(client, cmid, course_id)
    results: list[ReminderResult] = []
    for student in missing:
        try:
            client.send_message(student["user_id"], message_text)
            results.append({**student, "sent": True})
        except Exception:
            results.append({**student, "sent": False})
    return results


def remind_all_missing_students(
        client: MoodleClientProtocol,
        course_ids: list[CourseId],
        course_map: CourseMap,
        message_text: str,
        status: AssignmentStatus = "all",
) -> list[BulkReminderResult]:
    """Send a reminder to every student missing a submission, across all courses/assignments.

    Each student receives one message per assignment they haven't submitted.
    Each result: {course, assignment, user_id, fullname, sent}
    """
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn

    console = Console()
    assignments_list = list_assignments(client, course_ids, status=status)
    results: list[BulkReminderResult] = []

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Scanning…", total=len(assignments_list))

        for assign in assignments_list:
            cid = assign["course_id"]
            course_info = course_map.get(cid)
            course_short = course_info["shortname"] if course_info is not None else str(cid)
            progress.update(task, description=f"[cyan]{assign['name'][:50]}[/cyan]")

            try:
                missing = get_missing_submissions(client, assign["cmid"], cid)
            except Exception as exc:
                console.print(f"[yellow]  Warning: {assign['name']}: {exc}[/yellow]")
                progress.advance(task)
                continue

            for student in missing:
                try:
                    client.send_message(student["user_id"], message_text)
                    sent = True
                except Exception:
                    sent = False
                results.append({
                    "course": course_short,
                    "assignment": assign["name"],
                    "user_id": student["user_id"],
                    "fullname": student["fullname"],
                    "sent": sent,
                })

            progress.advance(task)

    return results


def get_due_soon(
        client: MoodleClientProtocol,
        course_ids: list[CourseId],
        course_map: CourseMap,
        days: int = 7,
) -> list[DueSoon]:
    """Return active assignments with a due date within the next `days` days.

    Assignments with no parseable due date are excluded.
    Results are sorted by days_left ascending (most urgent first).
    Each result: {course, cmid, assignment, due_date, submitted, days_left}
    """
    now = datetime.now()
    cutoff = now + timedelta(days=days)
    assignments_list = list_assignments(client, course_ids, status="active")

    results: list[DueSoon] = []
    for assign in assignments_list:
        due_dt = assign.get("due_dt")
        if due_dt is None:
            continue  # No parseable due date — cannot determine urgency
        if due_dt > cutoff:
            continue  # Due later than the requested window

        course_info = course_map.get(assign["course_id"])
        course_short = course_info["shortname"] if course_info is not None else str(assign["course_id"])
        days_left = (due_dt - now).days
        results.append({
            "course": course_short,
            "cmid": assign["cmid"],
            "assignment": assign["name"],
            "due_date": assign["due_text"],
            "submitted": assign["submitted_count"],
            "days_left": max(0, days_left),
        })

    results.sort(key=lambda r: r["days_left"])
    return results


def download_submissions(
        client: MoodleClientProtocol,
        course_ids: list[CourseId],
        course_map: CourseMap,
        status: AssignmentStatus = "all",
        out_dir: Path = Path("assignments"),
        ungraded_only: bool = False,
) -> list[DownloadResult]:
    """Download submitted files for all assignments in the given courses.

    course_map: {course_id: Course} — pass result of get_courses() keyed by id
    Output layout:
        {out_dir}/{course_short}/{active|past}/{assignment}/{student_name_id}/file

    Pass ungraded_only=True to skip already-graded submissions.
    Returns a list of result records (one per student-submission).
    """
    from rich.console import Console
    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

    console = Console()

    assignments = list_assignments(client, course_ids, status=status)
    if not assignments:
        console.print("[yellow]No assignments found.[/yellow]")
        return []

    submitted = [a for a in assignments if a["submitted_count"] > 0]
    console.print(
        f"Found [bold]{len(assignments)}[/bold] assignment(s) "
        f"([bold]{len(submitted)}[/bold] with submissions). "
        f"Fetching submission details…"
    )

    results: list[DownloadResult] = []
    total_files = 0

    with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
    ) as progress:
        task = progress.add_task("Scanning…", total=len(assignments))

        for assign in assignments:
            cid = assign["course_id"]
            course_info = course_map.get(cid)
            course_short = _safe_name(course_info["shortname"] if course_info is not None else str(cid))
            assign_dir = _safe_name(assign["name"])

            progress.update(task, description=f"[cyan]{assign['name'][:40]}[/cyan]")

            # Download instructor-attached brief files for this assignment
            try:
                brief_files = client.get_assignment_brief_files(assign["cmid"])
                if brief_files:
                    brief_dir = out_dir / course_short / assign["status"] / assign_dir / "_brief"
                    for f in brief_files:
                        dest = brief_dir / _safe_name(f["filename"])
                        try:
                            client.download_file(f["url"], dest)
                        except Exception as exc:
                            console.print(f"[red]  ✗ brief {f['filename']}: {exc}[/red]")
            except Exception as exc:
                console.print(f"[yellow]  Warning: could not fetch brief for {assign['name']}: {exc}[/yellow]")

            if assign["submitted_count"] == 0:
                progress.advance(task)
                continue

            try:
                submissions = client.get_assignment_submissions(assign["cmid"])
            except Exception as exc:
                console.print(f"[yellow]  Warning: {assign['name']}: {exc}[/yellow]")
                progress.advance(task)
                continue

            if ungraded_only:
                submissions = [s for s in submissions if is_ungraded(s)]

            for sub in submissions:
                uid = sub["user_id"]
                fullname = sub["fullname"]
                student_dir = _safe_name(f"{fullname}_{uid}")
                dest_dir = out_dir / course_short / assign["status"] / assign_dir / student_dir

                files_ok = 0
                files_err = 0
                for f in sub["files"]:
                    dest = dest_dir / _safe_name(f["filename"])
                    try:
                        client.download_file(f["url"], dest)
                        files_ok += 1
                        total_files += 1
                    except Exception as exc:
                        files_err += 1
                        console.print(f"[red]  ✗ {f['filename']}: {exc}[/red]")

                course_fullname = course_info["fullname"] if course_info is not None else str(cid)
                results.append({
                    "course": course_fullname,
                    "assignment": assign["name"],
                    "student": fullname,
                    "student_id": uid,
                    "files_ok": files_ok,
                    "files_err": files_err,
                    "path": str(dest_dir),
                })

            progress.advance(task)

    console.print(
        f"\n[green]Done.[/green] {total_files} file(s) saved under "
        f"[bold]{out_dir.resolve()}[/bold]"
    )
    return results

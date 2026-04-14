from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from moodlectl.client import MoodleClient

# Moodle displays due dates in this format: "Thursday, 26 March 2026, 11:59 PM"
_DUE_DATE_FMT = "%A, %d %B %Y, %I:%M %p"


def _parse_due(due_text: str) -> datetime | None:
    """Parse Moodle due date text to a datetime, or None if unparseable."""
    try:
        return datetime.strptime(due_text.strip(), _DUE_DATE_FMT)
    except ValueError:
        return None


def _safe_name(name: str) -> str:
    """Strip characters illegal in directory/file names, limit length."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name[:80] or "unnamed"


def list_assignments(
    client: MoodleClient,
    course_ids: list[int],
    status: str = "all",
) -> list[dict]:
    """Return assignments across courses filtered by status.

    status values: 'active' (future due date or no due date), 'past', 'all'
    Each result includes course info, assignment info, and parsed due date.
    """
    now = datetime.now()
    results = []

    for cid in course_ids:
        try:
            course_assignments = client.get_course_assignments(cid)
        except Exception as exc:
            # Don't abort the whole run for one inaccessible course
            continue

        # Look up course metadata for display
        # (courses are already fetched by the CLI; pass shortname via a lookup or leave blank)

        for assign in course_assignments:
            due_dt = _parse_due(assign["due_text"])
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


def download_submissions(
    client: MoodleClient,
    course_ids: list[int],
    course_map: dict[int, dict],
    status: str = "all",
    out_dir: Path = Path("assignments"),
) -> list[dict]:
    """Download submitted files for all assignments in the given courses.

    course_map: {course_id: {id, shortname, fullname}} — pass result of get_courses()
    Output layout:
        {out_dir}/{course_short}/{active|past}/{assignment}/{student_name_id}/file

    Returns a list of result records (one per student-submission).
    """
    from rich.console import Console
    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

    console = Console()

    assignments = list_assignments(client, course_ids, status=status)
    if not assignments:
        console.print("[yellow]No assignments found.[/yellow]")
        return []

    # Show a quick summary before starting the downloads
    submitted = [a for a in assignments if a["submitted_count"] > 0]
    console.print(
        f"Found [bold]{len(assignments)}[/bold] assignment(s) "
        f"([bold]{len(submitted)}[/bold] with submissions). "
        f"Fetching submission details…"
    )

    results: list[dict] = []
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
            course = course_map.get(cid, {})
            course_short = _safe_name(course.get("shortname") or str(cid))

            assign_dir = _safe_name(assign["name"])

            progress.update(
                task,
                description=f"[cyan]{assign['name'][:40]}[/cyan]",
            )

            # Always download the assignment brief files (instructor attachments)
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

            for sub in submissions:
                uid = sub["user_id"]
                fullname = sub["fullname"]
                student_dir = _safe_name(f"{fullname}_{uid}")
                dest_dir = (
                    out_dir / course_short / assign["status"] / assign_dir / student_dir
                )

                dl_results = []
                for f in sub["files"]:
                    dest = dest_dir / _safe_name(f["filename"])
                    try:
                        client.download_file(f["url"], dest)
                        dl_results.append({"filename": f["filename"], "ok": True})
                        total_files += 1
                    except Exception as exc:
                        dl_results.append({"filename": f["filename"], "ok": False, "error": str(exc)})
                        console.print(f"[red]  ✗ {f['filename']}: {exc}[/red]")

                results.append({
                    "course": course.get("fullname", str(cid)),
                    "assignment": assign["name"],
                    "student": fullname,
                    "student_id": uid,
                    "files_ok": sum(1 for d in dl_results if d["ok"]),
                    "files_err": sum(1 for d in dl_results if not d["ok"]),
                    "path": str(dest_dir),
                })

            progress.advance(task)

    console.print(
        f"\n[green]Done.[/green] {total_files} file(s) saved under "
        f"[bold]{out_dir.resolve()}[/bold]"
    )
    return results

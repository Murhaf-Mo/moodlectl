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
            "course": course_info.get("shortname", str(a["course_id"])),
            "assignment": a["name"],
            "status": a["status"],
            "due_date": a["due_text"] or "No due date",
            "submitted": a["submitted_count"],
        })

    print_table(rows, columns=["course", "assignment", "status", "due_date", "submitted"], fmt=output)


@app.command("download")
def download_submissions(
    course: list[int] = typer.Option(
        None, "--course", "-c", help="Course ID (repeatable). Omit for all your courses."
    ),
    status: str = typer.Option("all", "--status", "-s", help="active, past, or all"),
    out: Path = typer.Option(Path("assignments"), "--out", help="Output directory"),
):
    """Download submitted assignment files, organised by course and status.

    Output layout:
      {out}/{course}/{active|past}/{assignment}/{student_name_id}/file.pdf

    Examples:
      moodlectl assignments download
      moodlectl assignments download --course 568 --status active
      moodlectl assignments download --course 568 --status past --out ./archive
    """
    client, course_ids, course_map = _load(tuple(course or []))

    assignments_feature.download_submissions(
        client,
        course_ids,
        course_map=course_map,
        status=status,
        out_dir=out,
    )

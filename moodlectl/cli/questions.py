from __future__ import annotations

from collections import Counter
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.types import CourseId

app = typer.Typer(help="Question bank — import XML question banks into Moodle.")
console = Console(legacy_windows=False)


@app.command("import")
def import_questions(
        course: int = typer.Option(..., "--course", "-c", help="Course ID (from `courses list`)."),
        file: str = typer.Option(..., "--file", "-f", help="Path to a Moodle XML question bank."),
        dry_run: bool = typer.Option(False, "--dry-run",
                                     help="Validate locally and show preview; do not upload."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Import a Moodle XML question bank into a course's question bank.

    Validation runs in two stages before anything is uploaded:

      1. Local — parse the XML, count questions per type, list categories.
         Aborts on malformed XML, wrong root element, or zero questions.
      2. Remote — fetch the import form and confirm session + permission.

    Only after both pass does the command prompt for confirmation. Strict
    mode: any warning or error reported by Moodle aborts and surfaces the
    message; `stoponerror=1` is sent so Moodle stops on the first bad row.

    Examples:
      moodlectl questions import --course 581 --file quiz3_ch6_ch7.xml --dry-run
      moodlectl questions import -c 581 -f quiz3_ch6_ch7.xml -y
    """
    path = Path(file)
    if not path.is_file():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    # --- Stage 1: local XML validation ---
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        console.print(f"[red]Malformed XML:[/red] {exc}")
        raise typer.Exit(1)

    root = tree.getroot()
    if root.tag != "quiz":
        console.print(f"[red]Root element must be <quiz>, found <{root.tag}>.[/red]")
        raise typer.Exit(1)

    questions: list[tuple[str, str]] = []
    categories: list[str] = []
    for q in root.findall("question"):
        qtype = q.get("type", "?")
        if qtype == "category":
            categories.append(q.findtext("category/text", "") or "")
        else:
            name = q.findtext("name/text", "(unnamed)") or "(unnamed)"
            questions.append((qtype, name))

    if not questions:
        console.print("[red]No questions found in file.[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]File:[/bold] {path}")
    console.print(f"[bold]Course:[/bold] {course}")
    if categories:
        console.print("[bold]Categories declared in file:[/bold]")
        for c in categories:
            console.print(f"  - {c}")

    type_counts = Counter(t for t, _ in questions)
    tbl = Table(show_header=True, header_style="bold",
                title=f"{len(questions)} question(s) to import")
    tbl.add_column("Type")
    tbl.add_column("Count", justify="right")
    for t, n in sorted(type_counts.items()):
        tbl.add_row(t, str(n))
    console.print(tbl)

    if dry_run:
        console.print("[dim]Dry run — local validation only, no upload performed.[/dim]")
        return

    # --- Stage 2: remote pre-flight ---
    client = MoodleClient.from_config(Config.load())
    preflight_url = f"{client.base_url}/question/bank/importquestions/import.php"
    pf_resp = client._session.get(preflight_url, params={"courseid": course})
    if pf_resp.status_code != 200 or "/login/index.php" in pf_resp.url:
        console.print("[red]Pre-flight failed: session invalid or course not accessible.[/red]")
        console.print("[dim]Run `moodlectl auth login` and try again.[/dim]")
        raise typer.Exit(1)
    if "importquestions/import.php" not in pf_resp.text:
        console.print("[red]Pre-flight failed: import form not present "
                      "(missing permission on this course?).[/red]")
        raise typer.Exit(1)

    console.print("[green]Pre-flight OK[/green] — file parses, session valid, import form reachable.")

    # --- Confirm ---
    if not yes:
        confirmed = typer.confirm(
            f"Upload {len(questions)} question(s) to course {course}?",
            default=False,
        )
        if not confirmed:
            raise typer.Exit()

    # --- Upload ---
    try:
        result = client.import_question_bank(CourseId(course), str(path))
    except (RuntimeError, FileNotFoundError) as exc:
        console.print(f"[red]Import failed:[/red] {exc}")
        raise typer.Exit(1)

    # --- Strict check ---
    if result["errors"]:
        console.print("\n[red bold]Moodle reported errors:[/red bold]")
        for e in result["errors"]:
            console.print(f"  [red]X[/red] {e}")
        raise typer.Exit(1)
    if result["warnings"]:
        console.print("\n[yellow bold]Moodle reported warnings (strict mode aborts):[/yellow bold]")
        for w in result["warnings"]:
            console.print(f"  [yellow]![/yellow] {w}")
        raise typer.Exit(1)

    console.print(f"\n[green]Imported successfully.[/green]")
    if result["imported"]:
        console.print(f"Moodle confirmed [bold]{result['imported']}[/bold] question(s) imported.")
    console.print(f"[dim]Question bank: {result['response_url']}[/dim]")

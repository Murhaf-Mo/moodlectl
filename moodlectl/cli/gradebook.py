"""CLI for the Moodle gradebook setup (categories, grade items, calculations).

Phase 1 ships read-only commands:
    moodlectl gradebook show  --course 590
    moodlectl gradebook pull  --course 590 -o cst8285.yaml

Phase 2/3 will add `push` for declarative updates.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Column

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import gradebook as gradebook_feature
from moodlectl.types import CourseId

app = typer.Typer(
    help="Gradebook setup — inspect and (Phase 2+) push category / grade-item / "
         "calculation changes for a course."
)

console = Console(legacy_windows=False)

_DESC_WIDTH = 45
_COURSE_OPT = typer.Option(..., "--course", "-c", help="Course ID (from `courses list`).")


def _make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn(
            "[progress.description]{task.description}",
            table_column=Column(width=_DESC_WIDTH, no_wrap=True),
        ),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


@app.command("show")
def show_gradebook(course: int = _COURSE_OPT) -> None:
    """Print the gradebook tree (categories + items) for a course.

    Fast: one HTTP request, no per-node form fetches. For full settings dump
    use `gradebook pull -o file.yaml`.

    Examples:
      moodlectl gradebook show --course 590
    """
    client = MoodleClient.from_config(Config.load())
    try:
        tree = client.get_gradebook_tree(CourseId(course))
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    # Use plain print: render_tree includes `[cgN]` / `[igN]` tokens that
    # Rich would interpret as markup.
    print(gradebook_feature.render_tree(tree))


@app.command("pull")
def pull_gradebook(
        course: int = _COURSE_OPT,
        output: Optional[str] = typer.Option(
            None, "--output", "-o",
            help="Write YAML to this file path. Default: print to stdout.",
        ),
) -> None:
    """Export the full gradebook setup to a YAML file.

    Fetches per-category and per-item edit forms to capture droplow, idnumbers,
    calculations, weights, etc. Slow on large gradebooks — one HTTP request per
    node — but only needs to run once per change cycle.

    Edit the YAML, then use `gradebook push` (Phase 2) to apply changes.

    Examples:
      moodlectl gradebook pull --course 590
      moodlectl gradebook pull --course 590 -o cst8285.yaml
    """
    client = MoodleClient.from_config(Config.load())
    try:
        with _make_progress() as prog:
            task = prog.add_task("Fetching gradebook settings…", total=None)

            def _on_progress(current: int, total: int, name: str) -> None:
                desc = name[:_DESC_WIDTH].ljust(_DESC_WIDTH)
                prog.update(task, total=total, completed=current, description=f"[cyan]{desc}[/cyan]")

            yaml_text = gradebook_feature.pull(client, CourseId(course), progress=_on_progress)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if output:
        Path(output).write_text(yaml_text, encoding="utf-8")
        console.print(f"[green]Saved to {output}[/green]")
    else:
        print(yaml_text, end="")


@app.command("diff")
def diff_gradebook(
        file: str = typer.Argument(..., help="YAML file produced by `gradebook pull` (and edited)."),
        course: Optional[int] = typer.Option(None, "--course", "-c", help="Course ID override."),
) -> None:
    """Show the changes a `push` would apply, without touching Moodle.

    Examples:
      moodlectl gradebook diff cst8285.yaml
    """
    yaml_path = Path(file)
    if not yaml_path.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)
    yaml_text = yaml_path.read_text(encoding="utf-8")
    import yaml as _yaml
    parsed = _yaml.safe_load(yaml_text)
    yaml_course = parsed.get("course_id") if isinstance(parsed, dict) else None
    if course is not None:
        course_id = CourseId(course)
    elif yaml_course is not None:
        course_id = CourseId(int(yaml_course))
    else:
        console.print("[red]No course_id in YAML and no --course flag provided.[/red]")
        raise typer.Exit(1)

    client = MoodleClient.from_config(Config.load())
    try:
        changes = gradebook_feature.diff(client, course_id, yaml_text)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    console.print(f"[bold]Diff for course {int(course_id)}:[/bold]")
    print(gradebook_feature.render_diff(changes))
    console.print(f"\n[dim]{len(changes)} change(s) total.[/dim]")


@app.command("push")
def push_gradebook(
        file: str = typer.Argument(..., help="YAML file produced by `gradebook pull` (and edited)."),
        course: Optional[int] = typer.Option(None, "--course", "-c", help="Course ID override."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Show diff only, don't apply."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Apply without confirmation prompt."),
        debug: bool = typer.Option(False, "--debug", help="Print full Python traceback on error."),
        continue_on_error: bool = typer.Option(
            False, "--continue-on-error",
            help="Keep going when a single change fails; print a summary at the end.",
        ),
) -> None:
    """Apply a YAML file's changes to a course's gradebook.

    Before applying, writes a timestamped backup of the YAML to
    `<file>.bak.<UTC>`. The diff is printed and confirmation is required
    (unless `--yes`).

    Examples:
      moodlectl gradebook push cst8285.yaml --dry-run
      moodlectl gradebook push cst8285.yaml --yes
    """
    import datetime as _dt
    import traceback

    yaml_path = Path(file)
    if not yaml_path.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)
    yaml_text = yaml_path.read_text(encoding="utf-8")

    import yaml as _yaml
    parsed = _yaml.safe_load(yaml_text)
    yaml_course = parsed.get("course_id") if isinstance(parsed, dict) else None
    if course is not None:
        course_id = CourseId(course)
    elif yaml_course is not None:
        course_id = CourseId(int(yaml_course))
    else:
        console.print("[red]No course_id in YAML and no --course flag provided.[/red]")
        raise typer.Exit(1)

    client = MoodleClient.from_config(Config.load())
    try:
        changes = gradebook_feature.diff(client, course_id, yaml_text)
    except Exception as exc:
        if debug:
            traceback.print_exc()
        console.print(f"[red]Diff failed:[/red] {exc}")
        raise typer.Exit(1)

    console.print(f"[bold]Diff for course {int(course_id)}:[/bold]")
    print(gradebook_feature.render_diff(changes))
    console.print(f"\n[dim]{len(changes)} change(s) total.[/dim]")
    if not changes:
        console.print("[green]Already up to date — nothing to push.[/green]")
        return
    if dry_run:
        return

    if not yes:
        ok = typer.confirm("Apply these changes?", default=False)
        if not ok:
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(1)

    # Backup before applying.
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = yaml_path.with_suffix(yaml_path.suffix + f".bak.{stamp}")
    backup_path.write_text(yaml_text, encoding="utf-8")
    console.print(f"[dim]Backup written to {backup_path}[/dim]")

    failures: list[tuple[Any, str]] = []
    with _make_progress() as prog:
        task = prog.add_task("Applying changes…", total=len(changes))

        def _on(curr: int, tot: int, name: str) -> None:
            desc = name[:_DESC_WIDTH].ljust(_DESC_WIDTH)
            prog.update(task, total=tot, completed=curr, description=f"[cyan]{desc}[/cyan]")

        try:
            failures = gradebook_feature.push(
                client, course_id, changes, progress=_on, continue_on_error=continue_on_error,
            )
        except Exception as exc:
            if debug:
                traceback.print_exc()
            console.print(f"\n[red]Push aborted:[/red] {exc}")
            raise typer.Exit(1)

    if failures:
        console.print(f"\n[red]{len(failures)} change(s) failed:[/red]")
        for ch, msg in failures:
            console.print(f"  • {ch.label}\n      {msg}")
        raise typer.Exit(1)
    console.print(f"\n[green]Applied {len(changes)} change(s).[/green]")

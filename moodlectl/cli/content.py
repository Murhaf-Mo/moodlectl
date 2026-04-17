from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Column, Table
from rich.tree import Tree

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import content as content_feature
from moodlectl.features import content_yaml
from moodlectl.types import Cmid, CourseId

app = typer.Typer(help="Course content — list, hide, rename, delete modules and sections.")
section_app = typer.Typer(help="Section-level visibility and rename commands.")
app.add_typer(section_app, name="section")

console = Console(legacy_windows=False)

_DESC_WIDTH = 45  # fixed column width keeps the bar from jittering

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

_COURSE_OPT = typer.Option(..., "--course", "-c", help="Course ID (from `courses list`).")
_CMID_OPT = typer.Option(..., "--cmid", help="Course-module ID (from `content list`).")
_SECTION_OPT = typer.Option(..., "--section", "-s", help="Section number (0-indexed, from `content list`).")


# ---------------------------------------------------------------------------
# content list
# ---------------------------------------------------------------------------

@app.command("list")
def list_content(
    course: int = _COURSE_OPT,
    section: Optional[int] = typer.Option(None, "--section", "-s", help="Filter to one section number (0-indexed)."),
    type_: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by module type: forum, resource, url, page, assign, …"),
    hidden: bool = typer.Option(True, "--hidden/--no-hidden", help="Include hidden items (default: yes)."),
    output: str = typer.Option("tree", "--output", "-o", help="Output format: tree or json."),
) -> None:
    """List all sections and modules in a course.

    Examples:
      moodlectl content list --course 581
      moodlectl content list --course 581 --section 0
      moodlectl content list --course 581 --type resource --no-hidden
      moodlectl content list --course 581 --output json
    """
    client = MoodleClient.from_config(Config.load())
    try:
        sections = content_feature.get_sections(
            client, CourseId(course),
            section_num=section,
            modtype=type_,
            show_hidden=hidden,
        )
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if output == "json":
        import json
        # Convert to plain dicts for JSON serialisation
        out = [
            {**s, "id": int(s["id"]), "modules": [{**m, "cmid": int(m["cmid"])} for m in s["modules"]]}
            for s in sections
        ]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    # Tree output
    course_obj = next((c for c in client.get_courses() if c["id"] == course), None)
    title = f"Course {course}"
    if course_obj:
        title = f"[bold]{course_obj['shortname']}[/bold] (id={course})"
    tree = Tree(title)

    for sec in sections:
        vis_tag = "" if sec["visible"] else " [dim](hidden)[/dim]"
        sec_branch = tree.add(f"[cyan]\\[{sec['number']}][/cyan] {sec['name']}{vis_tag}")
        for mod in sec["modules"]:
            badge = f"[dim]{mod['modname'][:8].ljust(8)}[/dim]"
            vis = "[green]✓[/green]" if mod["visible"] else "[red]hidden[/red]"
            sec_branch.add(f"{badge}  cmid=[yellow]{mod['cmid']}[/yellow]  {mod['name']}  {vis}")

    console.print(tree)


# ---------------------------------------------------------------------------
# content show
# ---------------------------------------------------------------------------

@app.command("show")
def show_module(
    course: int = _COURSE_OPT,
    cmid: int = _CMID_OPT,
) -> None:
    """Show details for a single module.

    Examples:
      moodlectl content show --course 581 --cmid 18346
    """
    client = MoodleClient.from_config(Config.load())
    try:
        mod = content_feature.find_module(client, CourseId(course), Cmid(cmid))
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if mod is None:
        console.print(f"[red]Module cmid={cmid} not found in course {course}.[/red]")
        raise typer.Exit(1)

    tbl = Table(show_header=False)
    tbl.add_column("Field", style="bold")
    tbl.add_column("Value")
    tbl.add_row("cmid", str(mod["cmid"]))
    tbl.add_row("name", mod["name"])
    tbl.add_row("type", mod["modname"])
    tbl.add_row("visible", "[green]yes[/green]" if mod["visible"] else "[red]no[/red]")
    tbl.add_row("url", mod["url"] or "[dim]—[/dim]")
    console.print(tbl)


# ---------------------------------------------------------------------------
# content hide / content unhide
# ---------------------------------------------------------------------------

@app.command("hide")
def hide_module(
    course: int = _COURSE_OPT,
    cmid: int = _CMID_OPT,
) -> None:
    """Hide a module from students.

    Examples:
      moodlectl content hide --course 581 --cmid 18346
    """
    client = MoodleClient.from_config(Config.load())
    try:
        content_feature.set_module_visible(client, CourseId(course), Cmid(cmid), False)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Module {cmid} is now hidden.[/green]")


@app.command("unhide")
def unhide_module(
    course: int = _COURSE_OPT,
    cmid: int = _CMID_OPT,
) -> None:
    """Make a hidden module visible to students.

    Examples:
      moodlectl content unhide --course 581 --cmid 18346
    """
    client = MoodleClient.from_config(Config.load())
    try:
        content_feature.set_module_visible(client, CourseId(course), Cmid(cmid), True)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Module {cmid} is now visible.[/green]")


# ---------------------------------------------------------------------------
# content rename
# ---------------------------------------------------------------------------

@app.command("rename")
def rename_module(
    course: int = _COURSE_OPT,
    cmid: int = _CMID_OPT,
    name: str = typer.Option(..., "--name", "-n", help="New module name."),
) -> None:
    """Rename a module.

    Examples:
      moodlectl content rename --course 581 --cmid 18346 --name "Syllabus"
    """
    client = MoodleClient.from_config(Config.load())
    try:
        content_feature.rename_module(client, CourseId(course), Cmid(cmid), name)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Module {cmid} renamed to {name!r}.[/green]")


# ---------------------------------------------------------------------------
# content delete
# ---------------------------------------------------------------------------

@app.command("delete")
def delete_module(
    course: int = _COURSE_OPT,
    cmid: int = _CMID_OPT,
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt."),
) -> None:
    """Delete a module permanently.

    The module is moved to the Moodle recycle bin and can be restored from there.

    Examples:
      moodlectl content delete --course 581 --cmid 18346 --force
    """
    if not force:
        confirmed = typer.confirm(f"Delete module cmid={cmid}? It will go to the recycle bin.")
        if not confirmed:
            raise typer.Exit()

    client = MoodleClient.from_config(Config.load())
    try:
        content_feature.delete_module(client, CourseId(course), Cmid(cmid))
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Module {cmid} deleted (recoverable from Moodle recycle bin).[/green]")


# ---------------------------------------------------------------------------
# content section hide / unhide / rename
# ---------------------------------------------------------------------------

@section_app.command("hide")
def hide_section(
    course: int = _COURSE_OPT,
    section: int = _SECTION_OPT,
) -> None:
    """Hide a section from students.

    Examples:
      moodlectl content section hide --course 581 --section 1
    """
    client = MoodleClient.from_config(Config.load())
    try:
        content_feature.set_section_visible(client, CourseId(course), section, False)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Section {section} is now hidden.[/green]")


@section_app.command("unhide")
def unhide_section(
    course: int = _COURSE_OPT,
    section: int = _SECTION_OPT,
) -> None:
    """Make a hidden section visible to students.

    Examples:
      moodlectl content section unhide --course 581 --section 1
    """
    client = MoodleClient.from_config(Config.load())
    try:
        content_feature.set_section_visible(client, CourseId(course), section, True)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Section {section} is now visible.[/green]")


@section_app.command("rename")
def rename_section(
    course: int = _COURSE_OPT,
    section: int = _SECTION_OPT,
    name: str = typer.Option(..., "--name", "-n", help="New section name."),
) -> None:
    """Rename a section.

    Examples:
      moodlectl content section rename --course 581 --section 1 --name "Week 1: Intro"
    """
    client = MoodleClient.from_config(Config.load())
    try:
        content_feature.rename_section(client, CourseId(course), section, name)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Section {section} renamed to {name!r}.[/green]")


# ---------------------------------------------------------------------------
# content settings
# ---------------------------------------------------------------------------

@app.command("settings")
def module_settings(
    course: int = _COURSE_OPT,
    cmid: int = _CMID_OPT,
) -> None:
    """Show all editable settings for a module.

    Displays both human-readable field names (usable with `content set`) and
    their current values. Use this to inspect a module before editing.

    Examples:
      moodlectl content settings --course 581 --cmid 18867
    """
    client = MoodleClient.from_config(Config.load())
    try:
        raw_form = content_feature.get_module_settings(client, CourseId(course), Cmid(cmid))
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    from moodlectl.client.api import _build_module_settings_dynamic
    mod = content_feature.find_module(client, CourseId(course), Cmid(cmid))
    modname = mod["modname"] if mod else "unknown"
    all_settings = _build_module_settings_dynamic(raw_form)

    tbl = Table(title=f"Settings for cmid={cmid} ({modname})", show_header=True, header_style="bold")
    tbl.add_column("Field", style="bold cyan")
    tbl.add_column("Value")

    for key, val in all_settings.items():
        display = str(val) if val != "" else "[dim](not set)[/dim]"
        tbl.add_row(key, display)

    console.print(tbl)


# ---------------------------------------------------------------------------
# content set
# ---------------------------------------------------------------------------

@app.command("set")
def set_module_setting(
    course: int = _COURSE_OPT,
    cmid: int = _CMID_OPT,
    field: str = typer.Option(..., "--field", "-f", help="Setting name (from `content settings`)."),
    value: str = typer.Option(..., "--value", "-v", help="New value for the setting."),
) -> None:
    """Change a single setting on a module.

    Use `content settings` first to see available field names and current values.

    Examples:
      moodlectl content set --course 581 --cmid 18867 --field due_date --value "2026-05-01 23:59"
      moodlectl content set --course 581 --cmid 18867 --field max_grade --value 20
      moodlectl content set --course 581 --cmid 18867 --field description --value "<p>New text.</p>"
    """
    client = MoodleClient.from_config(Config.load())
    try:
        content_feature.set_module_setting(client, CourseId(course), Cmid(cmid), field, value)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Module {cmid} field {field!r} updated.[/green]")


# ---------------------------------------------------------------------------
# content pull
# ---------------------------------------------------------------------------

@app.command("pull")
def pull_content(
    course: int = _COURSE_OPT,
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Write YAML to this file path. Default: print to stdout."),
) -> None:
    """Export the full course structure to a YAML file.

    Edit the YAML file, then use `content push` to apply changes.
    Only name and visible fields are applied — all other fields are read-only.

    Examples:
      moodlectl content pull --course 581
      moodlectl content pull --course 581 -o course.yaml
    """
    client = MoodleClient.from_config(Config.load())
    try:
        with _make_progress() as prog:
            task = prog.add_task("Fetching module settings…", total=None)

            def _on_progress(current: int, total: int, name: str) -> None:
                desc = name[:_DESC_WIDTH].ljust(_DESC_WIDTH)
                prog.update(task, total=total, completed=current, description=f"[cyan]{desc}[/cyan]")

            yaml_text = content_yaml.pull(client, CourseId(course), progress=_on_progress)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if output:
        Path(output).write_text(yaml_text, encoding="utf-8")
        console.print(f"[green]Saved to {output}[/green]")
    else:
        print(yaml_text, end="")


# ---------------------------------------------------------------------------
# content push
# ---------------------------------------------------------------------------

@app.command("push")
def push_content(
    file: str = typer.Argument(..., help="Path to the YAML file produced by `content pull`."),
    course: Optional[int] = typer.Option(None, "--course", "-c", help="Course ID override (default: read from YAML course_id)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show changes without applying them."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply without confirmation prompt."),
) -> None:
    """Apply changes from a YAML file to a course.

    Computes a diff between the YAML and the live course state, shows a summary,
    then asks for confirmation before applying.

    Examples:
      moodlectl content push course.yaml --dry-run
      moodlectl content push course.yaml
      moodlectl content push course.yaml --yes
    """
    yaml_path = Path(file)
    if not yaml_path.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    yaml_text = yaml_path.read_text(encoding="utf-8")

    # Determine course_id
    import yaml as _yaml
    parsed = _yaml.safe_load(yaml_text)
    course_id_from_yaml = parsed.get("course_id") if isinstance(parsed, dict) else None

    if course is not None:
        course_id = CourseId(course)
    elif course_id_from_yaml is not None:
        course_id = CourseId(int(course_id_from_yaml))
    else:
        console.print("[red]No course_id in YAML and no --course flag provided.[/red]")
        raise typer.Exit(1)

    client = MoodleClient.from_config(Config.load())
    try:
        with _make_progress() as prog:
            task = prog.add_task("Computing diff…", total=None)

            def _on_diff_progress(current: int, total: int, name: str) -> None:
                desc = name[:_DESC_WIDTH].ljust(_DESC_WIDTH)
                prog.update(task, total=total, completed=current, description=f"[cyan]{desc}[/cyan]")

            changes, warnings = content_yaml.diff(client, course_id, yaml_text, progress=_on_diff_progress)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    # Print warnings
    for warn in warnings:
        console.print(f"[yellow]Warning:[/yellow] {warn}")

    if not changes:
        console.print("[green]No changes detected.[/green]")
        return

    # Print change summary
    console.print(f"\nChanges to apply for course {course_id}:\n")
    tbl = Table(show_header=True, header_style="bold")
    tbl.add_column("Op")
    tbl.add_column("Detail")
    for ch in changes:
        op_color = {
            "RENAME_MODULE": "blue", "RENAME_SECTION": "blue",
            "HIDE_MODULE": "yellow", "HIDE_SECTION": "yellow",
            "SHOW_MODULE": "green", "SHOW_SECTION": "green",
            "MOVE_MODULE": "cyan", "MOVE_SECTION": "cyan",
            "UPDATE_MODULE": "magenta",
            "UPDATE_COURSE": "blue",
        }.get(ch.kind, "white")
        tbl.add_row(f"[{op_color}]{ch.kind}[/{op_color}]", ch.label)
    console.print(tbl)
    console.print()

    if dry_run:
        console.print("[dim]Dry run — no changes applied.[/dim]")
        return

    if not yes:
        confirmed = typer.confirm(f"{len(changes)} change(s). Apply?", default=False)
        if not confirmed:
            raise typer.Exit()

    try:
        with _make_progress() as prog:
            task = prog.add_task("Applying changes…", total=len(changes))

            def _on_push_progress(current: int, total: int, label: str) -> None:
                desc = label[:_DESC_WIDTH].ljust(_DESC_WIDTH)
                prog.update(task, completed=current, description=f"[cyan]{desc}[/cyan]")

            content_yaml.push(client, changes, progress=_on_push_progress)
    except RuntimeError as exc:
        console.print(f"[red]Error during push:[/red] {exc}")
        raise typer.Exit(1)

    console.print(f"[green]Applied {len(changes)} change(s).[/green]")

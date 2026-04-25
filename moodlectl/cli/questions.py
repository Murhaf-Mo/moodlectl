from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import content as content_feature
from moodlectl.types import Cmid, CourseId

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


@app.command("to-quiz")
def to_quiz(
        course: int = typer.Option(..., "--course", "-c", help="Course ID."),
        section: Optional[int] = typer.Option(None, "--section", "-s",
                                              help="Section number for a new quiz (0-indexed). Ignored with --append-to-cmid."),
        name: Optional[str] = typer.Option(None, "--name", "-n",
                                           help="Quiz module name. Required for a new quiz; ignored with --append-to-cmid."),
        category: str = typer.Option(..., "--category",
                                     help="Question-bank category name to draw from (e.g. \"Quiz 3 — CH6 + CH7\")."),
        count: int = typer.Option(10, "--count", help="Number of random questions to pull (default: 10)."),
        open_at: Optional[str] = typer.Option(None, "--open",
                                              help="Open date \"YYYY-MM-DD HH:MM\" (e.g. \"2026-04-27 09:00\")."),
        close_at: Optional[str] = typer.Option(None, "--close",
                                               help="Close date \"YYYY-MM-DD HH:MM\" (e.g. \"2026-04-27 11:00\")."),
        password: Optional[str] = typer.Option(None, "--password",
                                               help="Quiz access password (students must enter it to start)."),
        time_limit: Optional[int] = typer.Option(None, "--time-limit",
                                                 help="Time limit in minutes (0 = no limit)."),
        attempts: Optional[int] = typer.Option(None, "--attempts",
                                               help="Maximum attempts per student (0 = unlimited)."),
        shuffle_answers: Optional[bool] = typer.Option(None, "--shuffle-answers/--no-shuffle-answers",
                                                       help="Shuffle answer choices within each question."),
        append_to_cmid: Optional[int] = typer.Option(None, "--append-to-cmid",
                                                     help="Attach to an existing quiz (cmid) instead of creating a new one."),
        visible: bool = typer.Option(False, "--visible/--hidden",
                                     help="Whether the quiz should be visible to students (default: hidden)."),
) -> None:
    """Create a quiz module wired to a question-bank category.

    Creates the quiz in the requested section, then attaches a random-question
    slot that pulls `--count` questions per attempt from the named category.
    Default visibility is hidden. With --append-to-cmid the command skips quiz
    creation entirely and just attaches another random pool to an existing
    quiz; in that case --section, --name, and the schedule/limit flags are
    ignored.

    Examples:
      moodlectl questions to-quiz -c 581 -s 10 -n "الاختبار 3" \\
          --category "Quiz 3 — CH6 + CH7" --count 10 --time-limit 60 --attempts 1
      moodlectl questions to-quiz -c 581 --append-to-cmid 20198 \\
          --category "Practice — CH7" --count 5
    """
    client = MoodleClient.from_config(Config.load())

    try:
        category_id, context_id = client.find_question_category(CourseId(course), category)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[dim]Resolved category {category!r} -> id={category_id} (context {context_id})[/dim]")

    if append_to_cmid:
        # Skip module creation; attach a new random pool to the existing quiz.
        try:
            client.add_random_questions_to_quiz(
                Cmid(append_to_cmid), category_id, context_id, count,
            )
        except RuntimeError as exc:
            console.print(f"[red]Failed to attach random questions:[/red] {exc}")
            raise typer.Exit(1)
        console.print(
            f"[green]Attached[/green] {count} random question(s) from "
            f"{category!r} to existing quiz cmid={append_to_cmid}."
        )
        console.print(f"\n[bold]Done.[/bold] Edit the quiz: "
                      f"{client.base_url}/mod/quiz/edit.php?cmid={append_to_cmid}")
        return

    if section is None or not name:
        console.print("[red]--section and --name are required when not using --append-to-cmid.[/red]")
        raise typer.Exit(1)

    quiz_settings: dict[str, str] = {}
    if open_at:
        quiz_settings["available_from"] = open_at
    if close_at:
        quiz_settings["due_date"] = close_at
    if password:
        quiz_settings["password"] = password
    if time_limit is not None:
        quiz_settings["time_limit_mins"] = str(time_limit)
    if attempts is not None:
        quiz_settings["attempts_allowed"] = str(attempts)
    if shuffle_answers is not None:
        quiz_settings["shuffle_answers"] = "1" if shuffle_answers else "0"

    try:
        cmid = content_feature.create_module(
            client, CourseId(course), section, "quiz", name, settings=quiz_settings,
        )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Failed to create quiz module:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Created quiz[/green] cmid={cmid} in section {section}.")
    if open_at or close_at:
        when = f"opens {open_at}" if open_at else ""
        if close_at:
            when = f"{when}, closes {close_at}" if when else f"closes {close_at}"
        console.print(f"[dim]Schedule: {when}.[/dim]")
    if time_limit is not None or attempts is not None or shuffle_answers is not None:
        bits: list[str] = []
        if time_limit is not None:
            bits.append(f"time limit {time_limit}m" if time_limit else "no time limit")
        if attempts is not None:
            bits.append(f"{attempts} attempt(s)" if attempts else "unlimited attempts")
        if shuffle_answers is not None:
            bits.append("shuffle answers on" if shuffle_answers else "shuffle answers off")
        console.print(f"[dim]Settings: {', '.join(bits)}.[/dim]")

    try:
        client.add_random_questions_to_quiz(Cmid(cmid), category_id, context_id, count)
    except RuntimeError as exc:
        console.print(f"[red]Failed to attach random questions:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Attached[/green] {count} random question(s) from {category!r}.")

    if not visible:
        try:
            content_feature.set_module_visible(client, CourseId(course), Cmid(cmid), False)
        except (RuntimeError, ValueError) as exc:
            console.print(f"[yellow]Quiz created but failed to hide:[/yellow] {exc}")
            raise typer.Exit(1)
        console.print("[dim]Quiz hidden from students.[/dim]")
    else:
        console.print("[dim]Quiz left visible.[/dim]")

    console.print(f"\n[bold]Done.[/bold] Edit the quiz: "
                  f"{client.base_url}/mod/quiz/edit.php?cmid={cmid}")


@app.command("list-categories")
def list_categories(
        course: int = typer.Option(..., "--course", "-c", help="Course ID."),
        output: str = typer.Option("tree", "--output", "-o",
                                   help="Output format: tree, table, json."),
) -> None:
    """List every question-bank category visible from a course, with counts.

    Categories nest by depth; tree output indents children. `(N)` is the
    number of questions in that category.
    """
    client = MoodleClient.from_config(Config.load())
    try:
        cats = client.list_question_categories(CourseId(course))
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if not cats:
        console.print("[yellow]No categories found.[/yellow]")
        return

    if output == "json":
        import json
        print(json.dumps(cats, ensure_ascii=False, indent=2))
        return

    if output == "table":
        tbl = Table(show_header=True, header_style="bold",
                    title=f"Question-bank categories in course {course}")
        tbl.add_column("ID", justify="right")
        tbl.add_column("Context", justify="right")
        tbl.add_column("Depth", justify="right")
        tbl.add_column("Name")
        tbl.add_column("Questions", justify="right")
        for c in cats:
            tbl.add_row(
                str(c["id"]), str(c["context_id"]), str(c["depth"]),
                c["name"], str(c["count"]),
            )
        console.print(tbl)
        return

    # Tree output (default)
    base_depth = min(c["depth"] for c in cats) if cats else 1
    for c in cats:
        indent = "  " * (c["depth"] - base_depth)
        console.print(
            f"{indent}[cyan]{c['name']}[/cyan]  "
            f"[dim]id={c['id']} ({c['count']})[/dim]"
        )


@app.command("list")
def list_questions(
        course: int = typer.Option(..., "--course", "-c", help="Course ID."),
        category: str = typer.Option(..., "--category", help="Question-bank category name (exact)."),
        output: str = typer.Option("table", "--output", "-o",
                                   help="Output format: table, json."),
) -> None:
    """List every question inside a question-bank category.

    Shows id, type, name, status, usage count, last-used timestamp.
    """
    client = MoodleClient.from_config(Config.load())
    try:
        cat_id, ctx_id = client.find_question_category(CourseId(course), category)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    try:
        questions = client.list_questions_in_category(CourseId(course), cat_id, ctx_id)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if not questions:
        console.print(f"[yellow]No questions in category {category!r}.[/yellow]")
        return

    if output == "json":
        import json
        print(json.dumps(questions, ensure_ascii=False, indent=2))
        return

    tbl = Table(show_header=True, header_style="bold",
                title=f"{len(questions)} question(s) in {category!r}")
    tbl.add_column("ID", justify="right")
    tbl.add_column("Type")
    tbl.add_column("Name")
    tbl.add_column("Status")
    tbl.add_column("Used", justify="right")
    tbl.add_column("Last used")
    for q in questions:
        tbl.add_row(
            str(q["id"]), q["type"], q["name"][:60],
            q["status"], str(q["usage"]), q["last_used"],
        )
    console.print(tbl)


@app.command("delete-category")
def delete_category(
        course: int = typer.Option(..., "--course", "-c", help="Course ID."),
        name: str = typer.Option(..., "--name", "-n",
                                 help="Question-bank category name to delete (exact match)."),
        force: bool = typer.Option(False, "--force", "-f", help="Skip the confirmation prompt."),
) -> None:
    """Delete a question-bank category and every question inside it.

    Resolves the category by name, lists its questions, bulk-deletes them, then
    deletes the now-empty category. This is irreversible — once questions are
    purged from the bank they cannot be recovered short of a fresh import.

    Examples:
      moodlectl questions delete-category -c 581 -n "Quiz 3 — CH6 + CH7"
      moodlectl questions delete-category -c 581 -n "Quiz 3 — CH6 + CH7" --force
    """
    client = MoodleClient.from_config(Config.load())
    try:
        category_id, context_id = client.find_question_category(CourseId(course), name)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    console.print(f"Resolved category {name!r} -> id={category_id} (context {context_id})")

    if not force:
        confirmed = typer.confirm(
            f"Delete category {name!r} and ALL its questions? This cannot be undone.",
            default=False,
        )
        if not confirmed:
            raise typer.Exit()

    try:
        result = client.delete_question_category(CourseId(course), category_id, context_id)
    except RuntimeError as exc:
        console.print(f"[red]Failed:[/red] {exc}")
        raise typer.Exit(1)

    console.print(
        f"[green]Deleted[/green] {result['questions_deleted']} question(s) from "
        f"the bank."
    )
    if result["category_deleted"]:
        console.print(f"[green]Category {name!r} removed.[/green]")
    else:
        console.print(
            f"[yellow]Category {name!r} still present — Moodle may have refused "
            f"deletion (e.g. it's the default category for this context).[/yellow]"
        )

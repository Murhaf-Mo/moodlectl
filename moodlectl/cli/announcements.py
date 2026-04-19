from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import announcements as announcements_feature
from moodlectl.output.formatters import console, print_table
from moodlectl.types import Cmid, CourseId

app = typer.Typer(help="Announcements — post to and manage course forum discussions.")


_COURSE_OPT = typer.Option(None, "--course", "-c", help="Course ID (auto-resolves the news forum).")
_FORUM_OPT = typer.Option(None, "--forum", help="Forum cmid (from `content list`) — overrides --course.")
_DISCUSSION_OPT = typer.Option(..., "--id", help="Discussion ID (from `announcements list`).")
_OUTPUT_OPT = typer.Option("table", "--output", "-o", help="Output format: table, json, or csv.")


@app.command("send")
def send(
        course: Optional[int] = _COURSE_OPT,
        forum: Optional[int] = _FORUM_OPT,
        subject: str = typer.Option(..., "--subject", "-s", help="Subject line."),
        message: Optional[str] = typer.Option(None, "--message", "-m",
                                              help="Message body (HTML by default)."),
        message_file: Optional[Path] = typer.Option(None, "--message-file",
                                                    help="Read the message body from a local file."),
        fmt: str = typer.Option("html", "--format", "-f",
                                help="Message format: html, plain, moodle, markdown."),
        group: int = typer.Option(-1, "--group",
                                  help="Group id to target (-1 = all groups)."),
        no_mail: bool = typer.Option(False, "--no-mail",
                                     help="Skip the 'mail now' notification."),
        no_subscribe: bool = typer.Option(False, "--no-subscribe",
                                          help="Don't subscribe the poster to replies."),
        pinned: bool = typer.Option(False, "--pinned", help="Pin the discussion to the top."),
        attach: Optional[list[str]] = typer.Option(None, "--attach",
                                                   help="Attach a local file (repeatable)."),
) -> None:
    """Post a new discussion to a forum.

    Use --course to auto-resolve the course's Announcements (news) forum;
    use --forum <cmid> to post to any other forum (e.g. a Q&A forum).

    Examples:
      moodlectl announcements send -c 581 -s "Midterm moved" -m "<p>Thursday 10am.</p>"
      moodlectl announcements send -c 581 -s "Week 6" --message-file week6.html --pinned
      moodlectl announcements send --forum 19850 -s "..." -m "..." --no-mail
      moodlectl announcements send -c 581 -s "Syllabus" -m "<p>See attached.</p>" --attach syllabus.pdf
      moodlectl announcements send -c 581 -s "Notes" --message-file notes.md --format markdown
    """
    if message and message_file:
        console.print("[red]Pass either --message or --message-file, not both.[/red]")
        raise typer.Exit(1)
    if message_file:
        if not message_file.is_file():
            console.print(f"[red]File not found: {message_file}[/red]")
            raise typer.Exit(1)
        body = message_file.read_text(encoding="utf-8")
    elif message:
        body = message
    else:
        console.print("[red]Provide --message or --message-file.[/red]")
        raise typer.Exit(1)

    client = MoodleClient.from_config(Config.load())
    try:
        discussion_id = announcements_feature.post_announcement(
            client,
            subject=subject,
            message=body,
            course_id=CourseId(course) if course is not None else None,
            forum_cmid=Cmid(forum) if forum is not None else None,
            mail_now=not no_mail,
            pinned=pinned,
            subscribe=not no_subscribe,
            message_format=fmt,
            group_id=group,
            attachments=list(attach) if attach else None,
        )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Posted. Discussion ID: [bold]{discussion_id}[/bold][/green]")


@app.command("list")
def list_(
        course: Optional[int] = _COURSE_OPT,
        forum: Optional[int] = _FORUM_OPT,
        limit: int = typer.Option(20, "--limit", "-n", help="Maximum discussions to show."),
        output: str = typer.Option("table", "--output", "-o",
                                   help="Output format: table, json, or csv."),
) -> None:
    """List recent discussions in a forum (newest first; pinned surface above).

    Examples:
      moodlectl announcements list -c 581
      moodlectl announcements list --forum 19850 --limit 5
      moodlectl announcements list -c 581 -o json
    """
    client = MoodleClient.from_config(Config.load())
    try:
        discussions = announcements_feature.list_announcements(
            client,
            course_id=CourseId(course) if course is not None else None,
            forum_cmid=Cmid(forum) if forum is not None else None,
            limit=limit,
        )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    rows = [
        {
            "id": d["id"],
            "subject": d["name"],
            "author": d["userfullname"],
            "modified": d["timemodified"],
            "pinned": "yes" if d["pinned"] else "",
        }
        for d in discussions
    ]
    print_table(rows, columns=["id", "subject", "author", "modified", "pinned"], fmt=output)  # type: ignore[arg-type]


@app.command("show")
def show(
        discussion_id: int = _DISCUSSION_OPT,
) -> None:
    """Show the full post thread for a discussion (root + replies).

    Examples:
      moodlectl announcements show --id 2456
    """
    client = MoodleClient.from_config(Config.load())
    try:
        posts = announcements_feature.view_announcement(client, discussion_id)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    if not posts:
        console.print("[yellow]No posts found.[/yellow]")
        return
    for i, p in enumerate(posts):
        tag = "[bold cyan]ROOT[/bold cyan]" if not p.get("parentid") else "[dim]reply[/dim]"
        header = Table(show_header=False, box=None)
        header.add_row("", tag)
        header.add_row("[bold]Subject[/bold]", p.get("subject", ""))
        header.add_row("[bold]Author[/bold]", p.get("author_fullname", ""))
        header.add_row("[bold]Posted[/bold]", p.get("timecreated_str", ""))
        header.add_row("[bold]Post ID[/bold]", str(p.get("id", "")))
        console.print(header)
        console.print(p.get("message", ""))
        if i < len(posts) - 1:
            console.print("─" * 60, style="dim")


@app.command("edit")
def edit(
        discussion_id: int = _DISCUSSION_OPT,
        subject: str = typer.Option(..., "--subject", "-s", help="New subject line."),
        message: Optional[str] = typer.Option(None, "--message", "-m",
                                              help="New HTML message body."),
        message_file: Optional[Path] = typer.Option(None, "--message-file",
                                                    help="Read new message body from a local file."),
) -> None:
    """Edit the subject and message of a discussion's root post.

    Examples:
      moodlectl announcements edit --id 2456 -s "Corrected date" -m "<p>Thursday 11am.</p>"
      moodlectl announcements edit --id 2456 -s "Notes v2" --message-file notes_v2.html
    """
    if message and message_file:
        console.print("[red]Pass either --message or --message-file, not both.[/red]")
        raise typer.Exit(1)
    if message_file:
        if not message_file.is_file():
            console.print(f"[red]File not found: {message_file}[/red]")
            raise typer.Exit(1)
        body = message_file.read_text(encoding="utf-8")
    elif message:
        body = message
    else:
        console.print("[red]Provide --message or --message-file.[/red]")
        raise typer.Exit(1)

    client = MoodleClient.from_config(Config.load())
    try:
        announcements_feature.edit_announcement(client, discussion_id, subject, body)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Discussion {discussion_id} updated.[/green]")


@app.command("delete")
def delete(
        discussion_id: int = _DISCUSSION_OPT,
        force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation."),
) -> None:
    """Delete a discussion (removes the root post and all replies).

    Examples:
      moodlectl announcements delete --id 2456 --force
    """
    if not force:
        confirmed = typer.confirm(
            f"Delete discussion {discussion_id}? This removes the root post and all replies.",
            default=False,
        )
        if not confirmed:
            raise typer.Exit()
    client = MoodleClient.from_config(Config.load())
    try:
        announcements_feature.delete_announcement(client, discussion_id)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Discussion {discussion_id} deleted.[/green]")

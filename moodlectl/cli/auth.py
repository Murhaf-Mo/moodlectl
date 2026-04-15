from __future__ import annotations

import typer
from rich.console import Console

from moodlectl.client import MoodleClient
from moodlectl.config import Config

app = typer.Typer(help="Session and authentication commands.")
console = Console(legacy_windows=False)


@app.command("check")
def check_session():
    """Check whether the current Moodle session is still valid.

    Makes a lightweight API call to verify the credentials in .env are active.
    Run this before starting a long operation to avoid session-expired errors mid-way.

    If the session has expired:
      1. Log back into Moodle in your browser.
      2. Open DevTools (F12) → Application → Cookies → copy the MoodleSession value.
      3. Open DevTools → Network → click any service.php request → copy sesskey from body.
      4. Paste both into your .env file and try again.

    Examples:
      moodlectl auth check
    """
    try:
        cfg = Config.load()
    except SystemExit:
        console.print("[red]Config missing or incomplete.[/red] Check your .env file.")
        raise typer.Exit(1)

    try:
        client = MoodleClient.from_config(cfg)
        courses = client.get_courses()
        console.print(
            f"[green]Session valid.[/green] "
            f"{len(courses)} course(s) accessible as configured."
        )
    except Exception as exc:
        console.print(f"[red]Session expired or invalid:[/red] {exc}")
        console.print(
            "\nRe-login in your browser, then update "
            "[bold]MOODLE_SESSION[/bold] and [bold]MOODLE_SESSKEY[/bold] in your .env file."
        )
        raise typer.Exit(1)

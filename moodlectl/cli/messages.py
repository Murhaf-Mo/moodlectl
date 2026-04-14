from __future__ import annotations

import typer

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.output.formatters import console

app = typer.Typer(help="Message commands")


@app.command("send")
def send(
    to: int = typer.Option(..., "--to", help="Recipient user ID"),
    text: str = typer.Option(..., "--text", help="Message text"),
):
    """Send a direct message to a user."""
    client = MoodleClient.from_config(Config.load())
    client.send_message(to, text)
    console.print(f"[green]Message sent to user {to}.[/green]")

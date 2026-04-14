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
    result = client.send_message(to, text)
    msg_id = result[0].get("msgid") if result else None
    if msg_id:
        console.print(f"[green]Message sent to user {to}. ID: {msg_id}[/green]")
    else:
        console.print(f"[green]Message sent to user {to}.[/green]")


@app.command("delete")
def delete(
    id: int = typer.Option(..., "--id", help="Message ID to delete"),
):
    """Delete (unsend) a previously sent message."""
    client = MoodleClient.from_config(Config.load())
    client.delete_message(id)
    console.print(f"[green]Message {id} deleted.[/green]")

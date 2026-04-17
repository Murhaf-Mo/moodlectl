from __future__ import annotations

import typer

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.output.formatters import console
from moodlectl.types import UserId

app = typer.Typer(help="Message commands")


@app.command("send")
def send(
        to: int = typer.Option(..., "--to", help="Recipient user ID (from `courses participants`)"),
        text: str = typer.Option(..., "--text", help="Message text"),
):
    """Send a direct Moodle message to a student or user.

    Use `courses participants` to find the user ID.

    Examples:
      moodlectl messages send --to 1557 --text "Your assignment is due tomorrow."
    """
    client = MoodleClient.from_config(Config.load())
    result = client.send_message(UserId(to), text)
    msg_id = result[0].get("msgid") if isinstance(result, list) and result else None
    if msg_id:
        console.print(f"[green]Message sent to user {to}. Message ID: {msg_id}[/green]")
    else:
        console.print(f"[green]Message sent to user {to}.[/green]")


@app.command("delete")
def delete(
        id: int = typer.Option(..., "--id", help="Message ID to delete"),
):
    """Delete (unsend) a previously sent message.

    Examples:
      moodlectl messages delete --id 98765
    """
    client = MoodleClient.from_config(Config.load())
    client.delete_message(id)
    console.print(f"[green]Message {id} deleted.[/green]")

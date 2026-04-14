from __future__ import annotations

from moodlectl.client import MoodleClient


def send_message(client: MoodleClient, user_id: int, text: str) -> dict:
    return client.send_message(user_id, text)


def delete_message(client: MoodleClient, message_id: int) -> None:
    client.delete_message(message_id)

from __future__ import annotations

from moodlectl.client import MoodleClient


def send_message(client: MoodleClient, user_id: int, text: str) -> dict:
    return client.send_message(user_id, text)

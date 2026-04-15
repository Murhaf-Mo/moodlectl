from __future__ import annotations

from moodlectl.types import JSON, MoodleClientProtocol, UserId


def send_message(client: MoodleClientProtocol, user_id: UserId, text: str) -> JSON:
    return client.send_message(user_id, text)


def delete_message(client: MoodleClientProtocol, message_id: int) -> None:
    client.delete_message(message_id)

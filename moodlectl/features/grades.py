from __future__ import annotations

from moodlectl.client import MoodleClient


def get_grades(client: MoodleClient, course_id: int, user_id: int = 0) -> dict:
    return client.get_grades(course_id, user_id)

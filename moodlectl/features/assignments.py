from __future__ import annotations

from moodlectl.client import MoodleClient


def get_assignments(client: MoodleClient, course_ids: list[int]) -> dict:
    return client.get_assignments(course_ids)

from __future__ import annotations

from moodlectl.client import MoodleClient


def list_courses(client: MoodleClient) -> list[dict]:
    return client.get_courses()


def get_participants(client: MoodleClient, course_id: int) -> list[dict]:
    raw = client.get_course_participants(course_id)
    return [_normalise(u) for u in raw]


def get_all_participants(client: MoodleClient) -> dict[int, list[dict]]:
    courses = list_courses(client)
    return {c["id"]: get_participants(client, c["id"]) for c in courses}


def _normalise(user: dict) -> dict:
    roles = [r["shortname"] for r in user.get("roles", [])]
    return {
        "id": user.get("id"),
        "fullname": user.get("fullname", ""),
        "email": user.get("email", ""),
        "roles": ", ".join(roles) if roles else "—",
        "lastaccess": user.get("lastaccess", 0),
    }

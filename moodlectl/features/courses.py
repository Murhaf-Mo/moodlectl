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
    raw_roles = user.get("roles", "")
    if isinstance(raw_roles, list):
        roles = ", ".join(r["shortname"] for r in raw_roles) or "—"
    else:
        roles = str(raw_roles) if raw_roles else "—"

    return {
        "id": user.get("id"),
        "fullname": user.get("fullname", ""),
        "email": user.get("email", ""),
        "roles": roles,
        "lastaccess": user.get("lastaccess", ""),
        "status": user.get("status", ""),
    }

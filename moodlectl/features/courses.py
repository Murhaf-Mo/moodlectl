from __future__ import annotations

import re

from moodlectl.client import MoodleClient


def list_courses(client: MoodleClient) -> list[dict]:
    """Return all enrolled courses from the Moodle API."""
    return client.get_courses()


def get_participants(
    client: MoodleClient,
    course_id: int,
    role: str = "",
    name: str = "",
) -> list[dict]:
    """Return participants for a course, optionally filtered by role and name.

    role: case-insensitive substring match on the roles field (e.g. "student")
    name: case-insensitive partial match on fullname
    """
    raw = client.get_course_participants(course_id)
    result = [_normalise(u) for u in raw]
    if role:
        result = [u for u in result if role.lower() in u["roles"].lower()]
    if name:
        result = [u for u in result if name.lower() in u["fullname"].lower()]
    return result


def get_all_participants(
    client: MoodleClient,
    role: str = "",
    name: str = "",
) -> dict[int, list[dict]]:
    """Return participants for every enrolled course, keyed by course ID."""
    courses = list_courses(client)
    return {c["id"]: get_participants(client, c["id"], role=role, name=name) for c in courses}


def get_inactive_students(
    client: MoodleClient,
    course_id: int,
    days: int = 14,
) -> list[dict]:
    """Return students who have not accessed the course in at least `days` days.

    lastaccess is scraped as a human-readable string from Moodle ("3 days 14 hours",
    "Never", etc.) and parsed on a best-effort basis. Entries whose lastaccess text
    cannot be parsed are included with inactive_days=None so nothing is silently dropped.

    Each result: {course, user_id, fullname, email, lastaccess, inactive_days}
    """
    participants = get_participants(client, course_id, role="student")
    results = []
    for p in participants:
        last = p.get("lastaccess", "")
        inactive_days = _parse_lastaccess_days(last)
        # Include the student if they're over the threshold OR if we can't parse the text
        if inactive_days is None or inactive_days >= days:
            results.append({
                "user_id": p["id"],
                "fullname": p["fullname"],
                "email": p["email"],
                "lastaccess": last or "—",
                "inactive_days": inactive_days if inactive_days is not None else "?",
            })
    # Sort: parseable days descending (most inactive first), unknowns last
    results.sort(
        key=lambda r: (r["inactive_days"] == "?", -(r["inactive_days"] if r["inactive_days"] != "?" else 0))
    )
    return results


def get_all_inactive_students(
    client: MoodleClient,
    days: int = 14,
    course_ids: list[int] | None = None,
) -> list[dict]:
    """Return inactive students across all (or selected) courses.

    Fetches participants per course and filters by the same lastaccess threshold.
    Each result includes a 'course' field (shortname) for context.

    Each result: {course, user_id, fullname, email, lastaccess, inactive_days}
    """
    all_courses = list_courses(client)
    if course_ids:
        all_courses = [c for c in all_courses if c["id"] in course_ids]

    results = []
    for course in all_courses:
        cid = course["id"]
        shortname = course.get("shortname", str(cid))
        participants = get_participants(client, cid, role="student")
        for p in participants:
            last = p.get("lastaccess", "")
            inactive_days = _parse_lastaccess_days(last)
            if inactive_days is None or inactive_days >= days:
                results.append({
                    "course": shortname,
                    "user_id": p["id"],
                    "fullname": p["fullname"],
                    "email": p["email"],
                    "lastaccess": last or "—",
                    "inactive_days": inactive_days if inactive_days is not None else "?",
                })

    # Sort: most inactive first across all courses
    results.sort(
        key=lambda r: (r["inactive_days"] == "?", -(r["inactive_days"] if r["inactive_days"] != "?" else 0))
    )
    return results


def _parse_lastaccess_days(text: str) -> int | None:
    """Parse a Moodle lastaccess string to approximate whole days since last access.

    Handles common Moodle formats (locale-independent where possible):
      "Never"              → 9999  (treat as very long ago)
      "3 days 14 hours"   → 3
      "2 weeks"           → 14
      "1 month"           → 30
      "5 hours 2 minutes" → 0     (today)
      "Yesterday"         → 1
      "Just now" / "X seconds" / "X minutes" → 0

    Returns None if the text is empty or doesn't match any known pattern.
    """
    if not text or not text.strip():
        return None

    t = text.strip().lower()

    if t == "never":
        return 9999

    # "yesterday" (may appear in some locales)
    if "yesterday" in t:
        return 1

    # Weeks: "2 weeks" → 14
    m = re.search(r"(\d+)\s*week", t)
    if m:
        return int(m.group(1)) * 7

    # Months: "1 month" → 30
    m = re.search(r"(\d+)\s*month", t)
    if m:
        return int(m.group(1)) * 30

    # Days: "3 days 14 hours" → 3
    m = re.search(r"(\d+)\s*day", t)
    if m:
        return int(m.group(1))

    # Hours / minutes / seconds → active today
    if re.search(r"\d+\s*(hour|min|sec)", t):
        return 0

    return None


def _normalise(user: dict) -> dict:
    """Normalise a raw participant dict from the client into a consistent shape.

    Handles both API format (roles as list of dicts) and scrape format (roles as string).
    """
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

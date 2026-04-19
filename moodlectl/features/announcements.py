from __future__ import annotations

import re
from pathlib import Path

from moodlectl.types import Cmid, CourseId, Discussion, ForumPost, MoodleClientProtocol

# Names that typically identify the auto-created news forum across locales.
_NEWS_FORUM_PATTERNS = re.compile(
    r"announcement|الإعلان|news|أخبار",
    re.IGNORECASE,
)

# Map human-friendly format names to Moodle's message-format integers.
_FORMATS: dict[str, int] = {
    "moodle": 0,
    "html": 1,
    "plain": 2,
    "markdown": 4,
}


def _format_to_int(name: str) -> int:
    key = name.strip().lower()
    if key not in _FORMATS:
        valid = ", ".join(sorted(_FORMATS))
        raise ValueError(f"Unknown message format {name!r}. Valid: {valid}")
    return _FORMATS[key]


def find_news_forum_cmid(client: MoodleClientProtocol, course_id: CourseId) -> Cmid:
    """Return the cmid of the course's Announcements (news) forum."""
    sections = client.get_course_sections(course_id)

    def _forums_in(section_num: int) -> list[tuple[str, Cmid]]:
        out: list[tuple[str, Cmid]] = []
        for s in sections:
            if s["number"] != section_num:
                continue
            for m in s["modules"]:
                if m["modname"] == "forum":
                    out.append((m["name"], m["cmid"]))
        return out

    for name, cmid in _forums_in(0):
        if _NEWS_FORUM_PATTERNS.search(name):
            return cmid

    section_zero = _forums_in(0)
    if section_zero:
        return section_zero[0][1]

    for s in sections:
        for m in s["modules"]:
            if m["modname"] == "forum":
                return m["cmid"]

    raise ValueError(
        f"Course {course_id} has no forum modules. Create one first, or pass --forum <cmid>."
    )


def _resolve_cmid(
        client: MoodleClientProtocol,
        course_id: CourseId | None,
        forum_cmid: Cmid | None,
) -> Cmid:
    if forum_cmid is not None and course_id is not None:
        raise ValueError("Pass either --course or --forum, not both.")
    if forum_cmid is not None:
        return forum_cmid
    if course_id is not None:
        return find_news_forum_cmid(client, course_id)
    raise ValueError("Pass --course (news forum) or --forum <cmid>.")


def post_announcement(
        client: MoodleClientProtocol,
        subject: str,
        message: str,
        course_id: CourseId | None = None,
        forum_cmid: Cmid | None = None,
        mail_now: bool = True,
        pinned: bool = False,
        subscribe: bool = True,
        message_format: str = "html",
        group_id: int = -1,
        attachments: list[str] | None = None,
) -> int:
    """Post a new discussion. Returns the new discussion id."""
    if not subject.strip():
        raise ValueError("subject cannot be empty")
    if not message.strip():
        raise ValueError("message cannot be empty")
    fmt = _format_to_int(message_format)
    attach_paths: list[str] = []
    for a in (attachments or []):
        p = Path(a)
        if not p.is_file():
            raise ValueError(f"Attachment not found: {a}")
        attach_paths.append(str(p.resolve()))
    cmid = _resolve_cmid(client, course_id, forum_cmid)
    return client.post_forum_discussion(
        cmid, subject, message,
        mail_now=mail_now,
        pinned=pinned,
        subscribe=subscribe,
        message_format=fmt,
        group_id=group_id,
        attachment_paths=attach_paths or None,
    )


def list_announcements(
        client: MoodleClientProtocol,
        course_id: CourseId | None = None,
        forum_cmid: Cmid | None = None,
        limit: int = 20,
) -> list[Discussion]:
    cmid = _resolve_cmid(client, course_id, forum_cmid)
    return client.list_forum_discussions(cmid, limit=limit)


def view_announcement(
        client: MoodleClientProtocol,
        discussion_id: int,
) -> list[ForumPost]:
    """Return the full post thread for a discussion (root post + any replies)."""
    return client.get_discussion_posts(discussion_id)


def edit_announcement(
        client: MoodleClientProtocol,
        discussion_id: int,
        subject: str,
        message: str,
) -> None:
    """Edit the subject and message of a discussion's root post."""
    if not subject.strip():
        raise ValueError("subject cannot be empty")
    if not message.strip():
        raise ValueError("message cannot be empty")
    client.update_discussion(discussion_id, subject, message)


def delete_announcement(client: MoodleClientProtocol, discussion_id: int) -> None:
    """Delete a discussion entirely (removes the root post and all replies)."""
    client.delete_discussion(discussion_id)

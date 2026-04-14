from __future__ import annotations

import re

from moodlectl.client import MoodleClient


def get_grade_report(
    client: MoodleClient,
    course_id: int,
    name: str = "",
) -> dict:
    """Return grade report for a course, optionally filtered by student name."""
    report = client.get_grade_report(course_id)

    if name:
        needle = name.lower()
        report["rows"] = [r for r in report["rows"] if needle in r["fullname"].lower()]

    return report


def shorten_columns(columns: list[str], max_len: int = 22) -> dict[str, str]:
    """Return {original_col: short_col} mapping for table display.

    Strips Arabic text (parenthesised non-ASCII blocks) and truncates to max_len.
    """
    mapping: dict[str, str] = {}
    for col in columns:
        # Remove Arabic/non-ASCII parenthesised suffixes like (البرمجة...)
        short = re.sub(r"\s*\([^\x00-\x7F]+\)", "", col).strip()
        if len(short) > max_len:
            short = short[:max_len - 1] + "…"
        mapping[col] = short
    return mapping

"""Aggregate cross-feature student reports. (COMING SOON)"""
from __future__ import annotations

from moodlectl.client import MoodleClient  # noqa: F401


def student_report(client: MoodleClient, student_id: int) -> None:
    raise NotImplementedError("Student reports coming soon")

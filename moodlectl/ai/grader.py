"""AI auto-grading. (COMING SOON)"""
from __future__ import annotations

from moodlectl.ai.client import AIClient  # noqa: F401


def grade_submission(ai: AIClient, submission: dict) -> tuple[float, str]:
    """Send submission to Claude, return (grade_0_to_100, feedback_text)."""
    raise NotImplementedError("AI grading coming soon")

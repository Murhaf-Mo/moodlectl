"""AI auto-reply to student messages. (COMING SOON)"""
from __future__ import annotations

from moodlectl.ai.client import AIClient  # noqa: F401


def generate_reply(ai: AIClient, message: dict) -> str:
    """Generate a reply to a student message using Claude."""
    raise NotImplementedError("AI auto-reply coming soon")

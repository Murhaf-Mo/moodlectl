"""AI auto-reply to student messages. (COMING SOON)"""
from __future__ import annotations

from moodlectl.ai.client import AIClient  # noqa: F401
from moodlectl.types import JSON


def generate_reply(ai: AIClient, message: JSON) -> str:
    """Generate a reply to a student message using Claude."""
    raise NotImplementedError("AI auto-reply coming soon")

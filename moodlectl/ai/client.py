"""Anthropic / Claude API wrapper. (COMING SOON — add ANTHROPIC_API_KEY to .env)"""
from __future__ import annotations


class AIClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise SystemExit("AI features require ANTHROPIC_API_KEY in .env")
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, system: str, user: str, model: str = "claude-sonnet-4-6") -> str:
        import anthropic
        message = self._client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Narrow to TextBlock — only that block type carries a .text attribute
        for block in message.content:
            if isinstance(block, anthropic.types.TextBlock):
                return block.text
        raise RuntimeError("Claude response contained no text block")

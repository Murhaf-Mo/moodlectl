from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

_MISSING_HINT = """
Missing Moodle credentials. Add them to your .env file:

  MOODLE_SESSION=<value>   → F12 → Application → Cookies → MoodleSession
  MOODLE_SESSKEY=<value>   → F12 → Network → any service.php request body

Re-login to Moodle in your browser first, then paste fresh values.
"""


@dataclass
class Config:
    base_url: str
    moodle_session: str
    moodle_sesskey: str
    anthropic_api_key: str

    @classmethod
    def load(cls) -> "Config":
        base_url = os.environ.get("MOODLE_BASE_URL", "https://mylms.cck.edu.kw")
        session = os.environ.get("MOODLE_SESSION", "")
        sesskey = os.environ.get("MOODLE_SESSKEY", "")

        if not session or not sesskey:
            raise SystemExit(_MISSING_HINT)

        return cls(
            base_url=base_url,
            moodle_session=session,
            moodle_sesskey=sesskey,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        )

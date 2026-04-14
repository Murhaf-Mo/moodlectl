from __future__ import annotations

import re

import requests

from moodlectl.config import Config


class MoodleClientBase:
    def __init__(self, base_url: str, session_cookie: str, sesskey: str) -> None:
        self.base_url = base_url
        self.sesskey = sesskey
        self._session = requests.Session()
        self._session.cookies.set("MoodleSession", session_cookie)
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": f"{base_url}/my/",
            "Origin": base_url,
            "Content-Type": "application/json",
        })

    @classmethod
    def from_config(cls, config: Config) -> "MoodleClientBase":
        return cls(config.base_url, config.moodle_session, config.moodle_sesskey)

    def refresh_sesskey(self) -> None:
        """Re-scrape sesskey from the dashboard. Call when you get sesskey errors."""
        resp = self._session.get(f"{self.base_url}/my/")
        match = re.search(r'"sesskey":"([^"]+)"', resp.text)
        if match:
            self.sesskey = match.group(1)
        else:
            raise RuntimeError(
                "Could not refresh sesskey — session may have expired.\n"
                "Re-login in your browser and update MOODLE_SESSION in .env"
            )

    def ajax(self, methodname: str, args: dict) -> dict | list:
        resp = self._session.post(
            f"{self.base_url}/lib/ajax/service.php",
            params={"sesskey": self.sesskey, "info": methodname},
            json=[{"index": 0, "methodname": methodname, "args": args}],
        )

        if resp.status_code == 403:
            raise RuntimeError(
                "403 Forbidden — session cookie has expired.\n"
                "Re-login in your browser and update MOODLE_SESSION in .env"
            )

        if not resp.text.strip():
            raise RuntimeError(
                "Empty response — session may have expired.\n"
                "Re-login in your browser and update MOODLE_SESSION in .env"
            )

        result = resp.json()
        if result[0].get("error"):
            raise RuntimeError(result[0]["exception"]["message"])

        return result[0]["data"]

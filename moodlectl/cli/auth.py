from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import typer
from dotenv import load_dotenv, set_key
from rich.console import Console

from moodlectl.client import MoodleClient
from moodlectl.config import Config

app = typer.Typer(help="Session and authentication commands.")
console = Console(legacy_windows=False)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _check_session_valid() -> tuple[bool, int]:
    """Return (is_valid, course_count). Never raises."""
    try:
        cfg = Config.load()
        client = MoodleClient.from_config(cfg)
        courses = client.get_courses()
        return True, len(courses)
    except BaseException:
        return False, 0


def _fetch_session_timeout(cfg: Config) -> int | None:
    """Scrape Moodle's configured session timeout (seconds) from the dashboard page."""
    try:
        resp = requests.get(
            f"{cfg.base_url}/my/",
            cookies={"MoodleSession": cfg.moodle_session},
            headers={"User-Agent": _UA},
            timeout=10,
            allow_redirects=True,
        )
        match = re.search(r'"sessiontimeout"\s*:\s*"?(\d+)"?', resp.text)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return None


def _save_credentials(env_path: Path, session: str, sesskey: str) -> None:
    set_key(str(env_path), "MOODLE_SESSION", session)
    set_key(str(env_path), "MOODLE_SESSKEY", sesskey)
    set_key(str(env_path), "MOODLE_SESSION_SAVED_AT", datetime.now(timezone.utc).isoformat())


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def _extract_via_selenium(base_url: str) -> tuple[str, str] | None:
    """Open Chrome via Selenium, wait for Moodle login, return (session, sesskey)."""
    from selenium import webdriver  # type: ignore[import]
    from selenium.webdriver.chrome.options import Options  # type: ignore[import]
    from selenium.webdriver.chrome.service import Service  # type: ignore[import]
    from webdriver_manager.chrome import ChromeDriverManager  # type: ignore[import]

    options = Options()
    options.add_argument("--start-maximized")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )

    try:
        driver.get(base_url)
        console.print(
            "\n[bold]Chrome is open.[/bold] Log in with your Moodle credentials.\n"
            "[dim]The window will close automatically once you're in.[/dim]\n"
        )

        deadline = time.time() + 300
        session_value: str | None = None

        while time.time() < deadline:
            if "/login" not in driver.current_url:
                for cookie in driver.get_cookies():
                    if cookie["name"] == "MoodleSession" and cookie["value"]:
                        session_value = cookie["value"]
                        break
            if session_value:
                break
            time.sleep(1)

        if not session_value:
            console.print("[red]Timed out waiting for login.[/red]")
            return None

        match = re.search(r'"sesskey"\s*:\s*"([^"]+)"', driver.page_source)
        if not match:
            driver.get(f"{base_url}/my/")
            time.sleep(2)
            match = re.search(r'"sesskey"\s*:\s*"([^"]+)"', driver.page_source)

        if not match:
            console.print("[red]Could not find sesskey on the page.[/red]")
            return None

        return session_value, match.group(1)

    finally:
        driver.quit()


@app.command("login")
def login() -> None:
    """Open Chrome and automatically save your Moodle session credentials.

    First checks if your current session is still valid — if so, skips the
    browser entirely. Otherwise opens Chrome for you to log in via Microsoft
    SSO. The window closes automatically once login is detected.

    Requires: pip install moodlectl[browser]

    Examples:
      moodlectl auth login
    """
    try:
        import selenium  # noqa: F401  type: ignore[import]
        import webdriver_manager  # noqa: F401  type: ignore[import]
    except ImportError:
        console.print(
            "[red]Browser login requires extra packages:[/red]\n\n"
            "  pip install moodlectl\\[browser]\n\n"
            "Then run [bold]moodlectl auth login[/bold] again."
        )
        raise typer.Exit(1)

    base_url = os.environ.get("MOODLE_BASE_URL", "https://moodle.example.com")
    env_path = Path(".env")

    # ── Pre-check: skip browser if session is already valid ───────────────────
    console.print("Checking existing session...")
    valid, count = _check_session_valid()
    if valid:
        console.print(
            f"[green]Session is still active[/green] — {count} course(s) accessible.\n"
            "No login needed. Run [bold]moodlectl auth check[/bold] to see expiry info."
        )
        return

    console.print("[yellow]Session expired or missing.[/yellow] Launching Chrome...\n")

    creds = _extract_via_selenium(base_url)

    if creds is None:
        console.print(
            "\n[red]Could not extract credentials.[/red]\n\n"
            "If the problem persists, paste values manually into [bold].env[/bold]:\n"
            "  MOODLE_SESSION  → F12 → Application → Cookies → MoodleSession\n"
            "  MOODLE_SESSKEY  → F12 → Network → any service.php request body"
        )
        raise typer.Exit(1)

    session, sesskey = creds
    _save_credentials(env_path, session, sesskey)
    console.print(
        f"\n[green]Saved to .env[/green]  "
        f"SESSION={session[:8]}…  SESSKEY={sesskey[:8]}…"
    )

    load_dotenv(override=True)
    try:
        cfg = Config.load()
        client = MoodleClient.from_config(cfg)
        courses = client.get_courses()
        console.print(
            f"[green bold]Session valid.[/green bold] "
            f"{len(courses)} course(s) accessible."
        )
    except Exception as exc:
        console.print(f"[yellow]Warning: session saved but verification failed:[/yellow] {exc}")


@app.command("check")
def check_session() -> None:
    """Check whether the current Moodle session is still valid and show expiry info.

    Reports session age (time since last login) and estimates time remaining
    based on Moodle's configured session timeout.

    If the session has expired, run:
      moodlectl auth login

    Examples:
      moodlectl auth check
    """
    try:
        cfg = Config.load()
    except SystemExit:
        console.print("[red]Config missing or incomplete.[/red] Run [bold]moodlectl auth login[/bold].")
        raise typer.Exit(1)

    try:
        client = MoodleClient.from_config(cfg)
        courses = client.get_courses()
    except Exception as exc:
        console.print(f"[red]Session expired or invalid:[/red] {exc}")
        console.print("\nRun [bold]moodlectl auth login[/bold] to refresh automatically.")
        raise typer.Exit(1)

    console.print(f"[green]Session valid.[/green] {len(courses)} course(s) accessible.")

    # ── Age & expiry estimate ─────────────────────────────────────────────────
    saved_at_raw = os.environ.get("MOODLE_SESSION_SAVED_AT", "")
    age_str = ""
    if saved_at_raw:
        try:
            saved_at = datetime.fromisoformat(saved_at_raw)
            elapsed = (datetime.now(timezone.utc) - saved_at).total_seconds()
            age_str = f"Session age: [bold]{_format_duration(elapsed)}[/bold]"
        except ValueError:
            pass

    timeout_sec = _fetch_session_timeout(cfg)
    if age_str:
        console.print(age_str)
    if timeout_sec and saved_at_raw:
        try:
            saved_at = datetime.fromisoformat(saved_at_raw)
            elapsed = (datetime.now(timezone.utc) - saved_at).total_seconds()
            remaining = timeout_sec - elapsed
            if remaining > 0:
                console.print(
                    f"Expires in: [bold cyan]{_format_duration(remaining)}[/bold cyan] "
                    f"(Moodle timeout: {_format_duration(timeout_sec)})"
                )
            else:
                console.print("[yellow]Session may be close to expiry — consider re-running auth login.[/yellow]")
        except ValueError:
            pass
    elif timeout_sec:
        console.print(f"Moodle session timeout: [bold]{_format_duration(timeout_sec)}[/bold]")


@app.command("set-url")
def set_url(
    url: str = typer.Argument(
        ...,
        help="Base URL of the Moodle instance (e.g. https://moodle.example.com).",
    ),
) -> None:
    """Set the Moodle base URL and save it to .env.

    The default URL is https://moodle.example.com. Use this command to point
    moodlectl at a different Moodle instance.

    Examples:
      moodlectl auth set-url https://moodle.example.com
    """
    url = url.rstrip("/")
    env_path = Path(".env")
    set_key(str(env_path), "MOODLE_BASE_URL", url)
    console.print(f"[green]MOODLE_BASE_URL set to:[/green] {url}")

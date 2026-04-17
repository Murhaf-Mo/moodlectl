from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

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
        # Prefer a lightweight GET check over an AJAX call so this works on any
        # Moodle version and doesn't fail if a specific web service isn't registered.
        resp = requests.get(
            f"{cfg.base_url}/my/",
            cookies={"MoodleSession": cfg.moodle_session},
            headers={"User-Agent": _UA},
            timeout=10,
            allow_redirects=True,
        )
        if "/login" in resp.url:
            return False, 0
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
        # Go directly to the login page so we start in a known state.
        driver.get(f"{base_url}/login/index.php")
        console.print(
            "\n[bold]Chrome is open.[/bold] Log in with your Moodle credentials.\n"
            "[dim]The window will close automatically once you're in.[/dim]\n"
        )

        # Use only scheme+host so the check works even if base_url has a path.
        parsed = urlparse(base_url)
        moodle_origin = f"{parsed.scheme}://{parsed.netloc}"
        deadline = time.time() + 300

        # Wait until the browser is on the Moodle server but off all login/auth pages.
        while time.time() < deadline:
            current = driver.current_url
            on_moodle = current.startswith(moodle_origin)
            on_login = any(p in current for p in ["/login/", "loggedout"])
            if on_moodle and not on_login:
                break
            time.sleep(1)
        else:
            console.print("[red]Timed out waiting for login.[/red]")
            return None

        # Brief pause so Moodle can finish writing the authenticated session cookie
        # (the Set-Cookie header is sent with the post-login redirect response, so
        # by the time the browser has navigated away from /login/ the cookie is set).
        time.sleep(2)

        session_value: str | None = None
        for cookie in driver.get_cookies():
            if cookie["name"] == "MoodleSession" and cookie["value"]:
                session_value = cookie["value"]
                break

        if not session_value:
            console.print("[red]Could not find MoodleSession cookie.[/red]")
            return None

        # Match "sesskey":"value", sesskey:"value", or sesskey: "value"
        match = re.search(r'"?sesskey"?\s*:\s*"([^"]+)"', driver.page_source)
        if not match:
            console.print(
                "[yellow]Could not find sesskey automatically.[/yellow]\n"
                "Use [bold]moodlectl auth set-session SESSION SESSKEY[/bold] to set it manually:\n"
                "  MoodleSession → F12 → Application → Cookies → MoodleSession\n"
                "  sesskey       → F12 → Network → any service.php request body"
            )
            return None

        return session_value, match.group(1)

    finally:
        driver.quit()


@app.command("login")
def login(
        session: str | None = typer.Option(
            None,
            "--session",
            help="MoodleSession cookie value (skips browser). Get it from F12 → Application → Cookies.",
        ),
        sesskey: str | None = typer.Option(
            None,
            "--sesskey",
            help="Moodle sesskey value (skips browser). Get it from F12 → Network → any service.php request body.",
        ),
) -> None:
    """Open Chrome and automatically save your Moodle session credentials.

    First checks if your current session is still valid — if so, skips the
    browser entirely. Otherwise opens Chrome for you to log in via Microsoft
    SSO. The window closes automatically once login is detected.

    Pass --session and --sesskey to skip the browser entirely and save
    credentials directly (same as [bold]auth set-session[/bold]).

    Requires browser: pip install moodlectl[browser]

    Examples:
      moodlectl auth login
      moodlectl auth login --session abc123 --sesskey p0AWOSwW1234
    """
    env_path = Path(".env")

    if session and sesskey:
        _save_credentials(env_path, session, sesskey)
        console.print(
            f"[green]Saved to .env[/green]  "
            f"SESSION={session[:8]}…  SESSKEY={sesskey[:8]}…"
        )
        load_dotenv(override=True)
        try:
            cfg = Config.load()
            resp = requests.get(
                f"{cfg.base_url}/my/",
                cookies={"MoodleSession": session},
                headers={"User-Agent": _UA},
                timeout=10,
                allow_redirects=True,
            )
            if "/login" in resp.url:
                console.print("[yellow]Warning: session appears invalid — server redirected to login.[/yellow]")
            else:
                console.print("[green bold]Session verified.[/green bold]")
        except Exception as exc:
            console.print(f"[yellow]Warning: could not verify session:[/yellow] {exc}")
        return

    try:
        import selenium  # noqa: F401  # pyright: ignore[reportUnusedImport]
        import webdriver_manager  # noqa: F401  # pyright: ignore[reportUnusedImport]
    except ImportError:
        console.print(
            "[red]Browser login requires extra packages:[/red]\n\n"
            "  pip install moodlectl\\[browser]\n\n"
            "Or set credentials manually:\n"
            "  moodlectl auth login --session SESSION --sesskey SESSKEY\n\n"
            "Then run [bold]moodlectl auth login[/bold] again."
        )
        raise typer.Exit(1)

    base_url = os.environ.get("MOODLE_BASE_URL", "https://school.moodledemo.net")
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
        resp = requests.get(
            f"{cfg.base_url}/my/",
            cookies={"MoodleSession": session},
            headers={"User-Agent": _UA},
            timeout=10,
            allow_redirects=True,
        )
        if "/login" in resp.url:
            console.print("[yellow]Warning: session saved but may not be valid yet — try auth check.[/yellow]")
        else:
            try:
                client = MoodleClient.from_config(cfg)
                courses = client.get_courses()
                console.print(
                    f"[green bold]Session valid.[/green bold] "
                    f"{len(courses)} course(s) accessible."
                )
            except Exception:
                console.print("[green bold]Session valid.[/green bold] (Courses unavailable via this API.)")
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
        resp = requests.get(
            f"{cfg.base_url}/my/",
            cookies={"MoodleSession": cfg.moodle_session},
            headers={"User-Agent": _UA},
            timeout=10,
            allow_redirects=True,
        )
        if "/login" in resp.url:
            raise RuntimeError("Session redirected to login page — session has expired.")
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
            help="Base URL of the Moodle instance (e.g. https://school.moodledemo.net).",
        ),
) -> None:
    """Set the Moodle base URL and save it to .env.

    Defaults to https://school.moodledemo.net (the public Moodle sandbox).
    Use this command to point moodlectl at your own Moodle instance.

    Examples:
      moodlectl auth set-url https://school.moodledemo.net
      moodlectl auth set-url https://moodle.yourschool.edu
    """
    parsed = urlparse(url)
    url = f"{parsed.scheme}://{parsed.netloc}"
    env_path = Path(".env")
    set_key(str(env_path), "MOODLE_BASE_URL", url)
    console.print(f"[green]MOODLE_BASE_URL set to:[/green] {url}")


@app.command("set-session")
def set_session(
        session: str = typer.Argument(..., help="MoodleSession cookie value."),
        sesskey: str = typer.Argument(..., help="Moodle sesskey value."),
) -> None:
    """Manually save a MoodleSession cookie and sesskey to .env.

    Use this when you cannot (or don't want to) use the browser-based login.
    Copy the values from your browser's developer tools:

    \\b
    How to find them:
      MoodleSession → F12 → Application → Cookies → MoodleSession
      sesskey       → F12 → Network → any request to service.php → request body

    Examples:
      moodlectl auth set-session abc123def456 p0AWOSwW1234
    """
    env_path = Path(".env")
    _save_credentials(env_path, session, sesskey)
    console.print(
        f"[green]Saved to .env[/green]  "
        f"SESSION={session[:8]}…  SESSKEY={sesskey[:8]}…"
    )

    load_dotenv(override=True)
    try:
        cfg = Config.load()
        resp = requests.get(
            f"{cfg.base_url}/my/",
            cookies={"MoodleSession": session},
            headers={"User-Agent": _UA},
            timeout=10,
            allow_redirects=True,
        )
        if "/login" in resp.url:
            console.print("[yellow]Warning: session appears invalid — server redirected to login.[/yellow]")
        else:
            console.print("[green bold]Session verified.[/green bold]")
    except Exception as exc:
        console.print(f"[yellow]Warning: could not verify session:[/yellow] {exc}")

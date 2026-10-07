"""Reusable Microsoft browser login; the original auth login remains available."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import typer
from dotenv import load_dotenv, set_key

from moodlectl.cli.auth import app, console, _save_credentials
from moodlectl.client import MoodleClient
from moodlectl.config import Config


def _credential_store():
    """Use the native encrypted store, never a plaintext keyring plugin."""
    import keyring
    store = keyring.get_keyring()
    expected = {"win32": "keyring.backends.Windows", "darwin": "keyring.backends.macOS"}
    if type(store).__module__ != expected.get(sys.platform):
        raise RuntimeError("Native credential store unavailable. Use interactive Microsoft sign-in.")
    return store


def _browser_profile() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return root / "moodlectl" / "microsoft-browser"


def _microsoft_password(base_url: str, username: str) -> str | None:
    try:
        from keyring.errors import KeyringError
    except ImportError:
        return None
    try:
        return _credential_store().get_password(f"moodlectl:microsoft:{base_url}", username)
    except (ImportError, RuntimeError, KeyringError):
        return None  # Browser sign-in still works without an available vault.


@app.command("microsoft-credentials")
def microsoft_credentials(
    username: str = typer.Option("", "--username", "-u"),
) -> None:
    """Save a Microsoft password in macOS Keychain or Windows Credential Manager.

    Password is requested with a hidden prompt, never through a command argument.
    """
    base_url = os.environ.get("MOODLE_BASE_URL", "").rstrip("/")
    if not base_url.startswith("https://"):
        raise typer.BadParameter("An HTTPS MOODLE_BASE_URL is required.")
    username = username or os.environ.get("MOODLE_MICROSOFT_USERNAME", "")
    if not username:
        username = typer.prompt("Microsoft email")
    store = _credential_store()
    password = typer.prompt("Microsoft password", hide_input=True, confirmation_prompt=True)
    try:
        store.set_password(f"moodlectl:microsoft:{base_url}", username, password)
    finally:
        password = None
    set_key(str(Path(".env")), "MOODLE_MICROSOFT_USERNAME", username)
    load_dotenv(Path(".env"), override=True)
    console.print("Microsoft credentials saved in the native credential store.")


@app.command("microsoft-login")
def microsoft_login(
    username: str = typer.Option("", "--username", "-u"),
    timeout: int = typer.Option(300, min=30, max=900),
) -> None:
    """Renew Moodle via a persistent profile and macOS/Windows credential store.

    Handles standard Microsoft email/password forms. MFA and other challenges
    remain interactive. Does not change the college's session lifetime policy.
    Original `auth login` remains the independent browser-login backup.
    """
    for attempt in range(2):
        try:
            _microsoft_login_once(username, timeout)
            return
        except RuntimeError:
            if attempt:
                raise
            console.print("Microsoft sign-in transfer was not verified; reconnecting once with the retained profile.")


def _microsoft_login_once(username: str, timeout: int) -> None:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    base_url = os.environ.get("MOODLE_BASE_URL", "").rstrip("/")
    if not base_url.startswith("https://"):
        raise typer.BadParameter("An HTTPS MOODLE_BASE_URL is required.")
    username = username or os.environ.get("MOODLE_MICROSOFT_USERNAME", "")
    if not username:
        raise typer.BadParameter("Supply --username for the first Microsoft login.")
    set_key(str(Path(".env")), "MOODLE_MICROSOFT_USERNAME", username)
    profile = _browser_profile()
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    options = Options()
    options.add_argument(f"--user-data-dir={profile}")
    options.add_argument("--start-maximized")
    options.add_experimental_option("prefs", {"credentials_enable_service": False, "profile.password_manager_enabled": False})
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    host = urlparse(base_url).hostname
    password = _microsoft_password(base_url, username)
    entered_email = entered_password = False
    last_stage = ""
    try:
        driver.get(f"{base_url}/my/")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                current = urlparse(driver.current_url)
                if current.hostname == host:
                    ready = driver.execute_script(
                        'return !!document.querySelector("a[href*=logout]") '
                        '&& typeof M !== "undefined" && !!M.cfg.sesskey;'
                    )
                    if ready and "/auth/" not in current.path:
                        break
                    links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/auth/oidc/"]')
                    if links:
                        links[0].click()
                        continue
                    stage = "Waiting for Moodle sign-in. Original auth login is also available."
                elif current.hostname in {"login.microsoftonline.com", "login.live.com"}:
                    emails = driver.find_elements(By.CSS_SELECTOR, 'input[type="email"]')
                    passwords = driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')
                    if emails and emails[0].is_displayed() and not entered_email:
                        emails[0].send_keys(username)
                        driver.find_element(By.ID, "idSIButton9").click()
                        entered_email = True
                        continue
                    if passwords and passwords[0].is_displayed() and password and not entered_password:
                        passwords[0].send_keys(password)
                        driver.find_element(By.ID, "idSIButton9").click()
                        entered_password = True
                        continue
                    stage = "Complete any Microsoft MFA, account selection or Stay signed in prompt in Chrome."
                else:
                    stage = "Waiting for the college sign-in redirect."
                if stage != last_stage:
                    console.print(stage)
                    last_stage = stage
            except Exception:
                # Redirects replace the document while it is being inspected.
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Microsoft sign-in timed out. Use auth login as backup.")

        time.sleep(2)
        cookies = driver.get_cookies()
        session = next(c["value"] for c in cookies if c["name"] == "MoodleSession")
        sesskey = driver.execute_script("return M.cfg.sesskey")
        env_path = Path(".env")
        set_key(str(env_path), "MOODLE_BROWSER_COOKIES", json.dumps(cookies))
        set_key(str(env_path), "MOODLE_BROWSER_USER_AGENT", driver.execute_script("return navigator.userAgent"))
        _save_credentials(env_path, session, sesskey, preserve_browser=True)
        load_dotenv(env_path, override=True)
        client = MoodleClient.from_config(Config.load())
        response = client._session.get(f"{base_url}/my/", timeout=20)
        console.print(f"Browser authenticated; CTL verification HTTP {response.status_code}, path {urlparse(response.url).path}.")
        if response.status_code >= 400:
            raise RuntimeError("Moodle returned an error while verifying the transferred session.")
        if "/login/" in urlparse(response.url).path:
            raise RuntimeError("Moodle rejected the transferred session; login was not verified.")
        courses = client.get_courses()
        if not courses:
            raise RuntimeError("Sign-in could not be verified against an accessible course.")
        console.print(f"Microsoft login verified: {len(courses)} accessible courses. Browser profile retained for reconnection.")
    finally:
        password = None
        driver.quit()

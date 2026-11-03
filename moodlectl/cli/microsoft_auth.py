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

from moodlectl.cli.auth import _save_credentials, app, console
from moodlectl.client import MoodleClient
from moodlectl.config import Config


def _credential_store():
    """Use the native encrypted store, never a plaintext keyring plugin."""
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError(
            "Credential storage requires the browser extra. "
            'Install with: pip install "moodlectl[browser]"'
        ) from exc
    if sys.platform == "darwin":
        # Select Keychain explicitly: a user's global keyring configuration may
        # select a chainer, null backend, or another application's plugin.
        from keyring.backends.macOS import Keyring

        return Keyring()
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


def _handle_microsoft_prompt(driver, username: str) -> str | None:
    """Handle only account selection and Microsoft's explicit KMSI prompt.

    The primary submit button is also used for consent and MFA, so its presence
    alone must never trigger a click. Unknown pages remain interactive.
    """
    from selenium.webdriver.common.by import By

    current = urlparse(driver.current_url)
    if current.scheme != "https" or current.hostname not in {
        "login.microsoftonline.com", "login.live.com"
    }:
        return None

    def visible(selector):
        return [
            element for element in driver.find_elements(By.CSS_SELECTOR, selector)
            if element.is_displayed() and element.is_enabled()
        ]

    if visible("#KmsiDescription, #KmsiTitle, #kmsiTitle"):
        buttons = visible("#idSIButton9")
        if buttons:
            buttons[0].click()
            return "stay-signed-in"

    if visible("#tilesHolder"):
        accounts = [
            element for element in visible('#tilesHolder [role="button"][data-test-id]')
            if (element.get_attribute("data-test-id") or "").strip().casefold()
            == username.strip().casefold()
        ]
        # When Microsoft lists both personal and work accounts for one email,
        # prefer the work/school identity used by the college's Moodle SSO.
        work_accounts = [
            element for element in accounts if element.get_attribute("data-test-idp") == "0"
        ]
        candidates = work_accounts or accounts
        if len(candidates) == 1:
            candidates[0].click()
            return "account"
        if not accounts:
            others = visible("#otherTile")
            if others:
                others[0].click()
                return "another-account"
    return None


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
    try:
        store = _credential_store()
    except (ImportError, RuntimeError) as exc:
        console.print(str(exc), markup=False)
        raise typer.Exit(1) from exc
    password = typer.prompt("Microsoft password", hide_input=True, confirmation_prompt=True)
    try:
        store.set_password(f"moodlectl:microsoft:{base_url}", username, password)
    except Exception as exc:
        # Backends may include sensitive values in exception messages. Report
        # only recovery instructions, never the backend's raw exception.
        console.print(
            "Could not save Microsoft credentials. Unlock macOS Keychain or "
            "Windows Credential Manager and allow access, then retry. "
            "No Microsoft login configuration was saved."
        )
        raise typer.Exit(1) from exc
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

    Handles Microsoft email/password, account selection and Stay signed in.
    MFA and other challenges remain interactive. Does not change the college's
    session lifetime policy.
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
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
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
                    prompt = _handle_microsoft_prompt(driver, username)
                    if prompt:
                        if prompt in {"account", "another-account"}:
                            entered_email = entered_password = False
                        if prompt != last_stage:
                            console.print({
                                "account": "Selected the configured Microsoft account.",
                                "another-account": "Opening sign-in for the configured Microsoft account.",
                                "stay-signed-in": "Accepted Microsoft's Stay signed in prompt.",
                            }[prompt])
                            last_stage = prompt
                        time.sleep(1)
                        continue
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
                    stage = "Waiting for a Microsoft sign-in redirect or an interactive challenge in Chrome."
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

from unittest.mock import Mock, PropertyMock, patch

import pytest
import typer
from typer.testing import CliRunner

from moodlectl.cli.auth import _check_session_valid
from moodlectl.cli.main import app
from moodlectl.cli.microsoft_auth import (
    _browser_profile,
    _credential_store,
    _handle_microsoft_prompt,
    microsoft_login,
)


def _prompt_driver(elements, url="https://login.microsoftonline.com/common/login"):
    driver = Mock()
    driver.current_url = url
    driver.find_elements.side_effect = lambda by, selector: elements.get(selector, [])
    return driver


def _account(email, idp="0"):
    element = Mock()
    element.get_attribute.side_effect = {"data-test-id": email, "data-test-idp": idp}.get
    return element


def test_account_selection_matches_exact_email_and_prefers_work_identity():
    wrong = _account("other@example.com")
    personal = _account("Teacher@example.com", "1")
    work = _account("teacher@example.com")
    other_button = Mock()
    driver = _prompt_driver({
        "#tilesHolder": [Mock()],
        '#tilesHolder [role="button"][data-test-id]': [wrong, personal, work],
        "#otherTile": [other_button],
    })
    assert _handle_microsoft_prompt(driver, "TEACHER@example.com") == "account"
    work.click.assert_called_once()
    wrong.click.assert_not_called()
    personal.click.assert_not_called()
    other_button.click.assert_not_called()


def test_unlisted_account_uses_another_account_instead_of_wrong_identity():
    wrong = _account("teacher@example.com.attacker.test")
    another = Mock()
    driver = _prompt_driver({
        "#tilesHolder": [Mock()],
        '#tilesHolder [role="button"][data-test-id]': [wrong],
        "#otherTile": [another],
    })
    assert _handle_microsoft_prompt(driver, "teacher@example.com") == "another-account"
    another.click.assert_called_once()
    wrong.click.assert_not_called()


def test_ambiguous_account_selection_remains_interactive():
    accounts = [_account("teacher@example.com"), _account("teacher@example.com")]
    driver = _prompt_driver({
        "#tilesHolder": [Mock()],
        '#tilesHolder [role="button"][data-test-id]': accounts,
    })
    assert _handle_microsoft_prompt(driver, "teacher@example.com") is None
    for account in accounts:
        account.click.assert_not_called()


@pytest.mark.parametrize("url", [
    "https://login.microsoftonline.com/kmsi",
    "https://login.live.com/ppsecure/post.srf",
])
def test_explicit_stay_signed_in_is_accepted(url):
    button = Mock()
    driver = _prompt_driver({
        "#KmsiDescription, #KmsiTitle, #kmsiTitle": [Mock()],
        "#idSIButton9": [button],
    }, url)
    assert _handle_microsoft_prompt(driver, "teacher@example.com") == "stay-signed-in"
    button.click.assert_called_once()


@pytest.mark.parametrize("url", [
    "http://login.microsoftonline.com/kmsi",
    "https://login.microsoftonline.com.attacker.test/kmsi",
    "https://moodle.example.com/kmsi",
])
def test_prompt_automation_rejects_untrusted_pages(url):
    driver = _prompt_driver({}, url)
    assert _handle_microsoft_prompt(driver, "teacher@example.com") is None
    driver.find_elements.assert_not_called()


def test_generic_submit_does_not_accept_mfa_or_consent():
    button = Mock()
    driver = _prompt_driver({"#idSIButton9": [button]})
    assert _handle_microsoft_prompt(driver, "teacher@example.com") is None
    button.click.assert_not_called()


def test_hidden_prompt_and_disabled_button_are_not_clicked():
    marker = Mock()
    marker.is_displayed.return_value = False
    button = Mock()
    driver = _prompt_driver({
        "#KmsiDescription, #KmsiTitle, #kmsiTitle": [marker],
        "#idSIButton9": [button],
    })
    assert _handle_microsoft_prompt(driver, "teacher@example.com") is None
    marker.is_displayed.return_value = True
    button.is_enabled.return_value = False
    assert _handle_microsoft_prompt(driver, "teacher@example.com") is None
    button.click.assert_not_called()


def test_auth_login_prefers_configured_microsoft_login(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOODLE_MICROSOFT_USERNAME", "teacher@example.com")
    with patch("moodlectl.cli.auth._check_session_valid", return_value=(False, 0)), patch(
        "moodlectl.cli.microsoft_auth.microsoft_login"
    ) as microsoft, patch("moodlectl.cli.auth._extract_via_selenium") as backup:
        result = CliRunner().invoke(app, ["auth", "login"])
    assert result.exit_code == 0
    microsoft.assert_called_once_with(username="teacher@example.com", timeout=300)
    backup.assert_not_called()


def test_original_browser_can_be_requested_or_used_after_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOODLE_MICROSOFT_USERNAME", "teacher@example.com")
    monkeypatch.delenv("MOODLE_USERNAME", raising=False)
    monkeypatch.delenv("MOODLE_PASSWORD", raising=False)
    for arguments, expected_calls in [(["auth", "login"], 1), (["auth", "login", "--fresh-browser"], 0)]:
        with patch("moodlectl.cli.auth._check_session_valid", return_value=(False, 0)), patch(
            "moodlectl.cli.microsoft_auth.microsoft_login", side_effect=RuntimeError("Sign-in unavailable")
        ) as microsoft, patch("moodlectl.cli.auth._extract_via_selenium", return_value=None) as backup:
            result = CliRunner().invoke(app, arguments)
        assert result.exit_code == 1
        assert microsoft.call_count == expected_calls
        backup.assert_called_once()


def test_server_error_is_not_a_valid_session():
    client = Mock()
    client._session.get.return_value = Mock(status_code=500, url="https://moodle.example.com/my/")
    with patch("moodlectl.cli.auth.Config.load"), patch(
        "moodlectl.cli.auth.MoodleClient.from_config", return_value=client
    ):
        assert _check_session_valid() == (False, 0)
    client.get_courses.assert_not_called()


def test_reconnect_retains_profile_and_validates_before_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("MOODLE_BASE_URL", "https://moodle.example.com")
    driver = Mock()
    type(driver).current_url = PropertyMock(return_value="https://moodle.example.com/my/")
    driver.get_cookies.return_value = [{"name": "MoodleSession", "value": "session", "domain": "moodle.example.com", "path": "/"}]
    driver.execute_script.side_effect = [True, "key", "Browser UA"]
    client = Mock()
    client._session.get.return_value = Mock(status_code=200, url="https://moodle.example.com/my/")
    client.get_courses.return_value = [{"id": 905}]
    with patch("selenium.webdriver.Chrome", return_value=driver) as chrome, patch(
        "webdriver_manager.chrome.ChromeDriverManager"
    ) as manager, patch("moodlectl.cli.microsoft_auth._microsoft_password", return_value="vault-secret"), patch(
        "moodlectl.cli.microsoft_auth.time.sleep"
    ), patch("moodlectl.cli.microsoft_auth.Config.load"), patch(
        "moodlectl.cli.microsoft_auth.MoodleClient.from_config", return_value=client
    ):
        manager.return_value.install.return_value = "chromedriver"
        microsoft_login(username="teacher@example.com", timeout=30)
    options = chrome.call_args.kwargs["options"]
    assert any("--user-data-dir=" in argument for argument in options.arguments)
    assert options.experimental_options["prefs"]["profile.password_manager_enabled"] is False
    assert "vault-secret" not in (tmp_path / ".env").read_text()
    assert driver.get.call_count == 1
    client.get_courses.assert_called_once()
    driver.quit.assert_called_once()


def test_reconnect_advances_through_account_and_stay_signed_in(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOODLE_BASE_URL", "https://moodle.example.com")
    page = ["account"]
    account = _account("teacher@example.com")
    account.click.side_effect = lambda: page.__setitem__(0, "kmsi")
    yes = Mock()
    yes.click.side_effect = lambda: page.__setitem__(0, "moodle")
    driver = Mock()
    type(driver).current_url = PropertyMock(side_effect=lambda: (
        "https://moodle.example.com/my/" if page[0] == "moodle"
        else "https://login.microsoftonline.com/" + page[0]
    ))
    screens = {
        "account": {
            "#tilesHolder": [Mock()],
            '#tilesHolder [role="button"][data-test-id]': [account],
        },
        "kmsi": {
            "#KmsiDescription, #KmsiTitle, #kmsiTitle": [Mock()],
            "#idSIButton9": [yes],
        },
    }
    driver.find_elements.side_effect = lambda by, selector: screens[page[0]].get(selector, [])
    driver.get_cookies.return_value = [{"name": "MoodleSession", "value": "session"}]
    driver.execute_script.side_effect = [True, "key", "Browser UA"]
    client = Mock()
    client._session.get.return_value = Mock(status_code=200, url="https://moodle.example.com/my/")
    client.get_courses.return_value = [{"id": 905}]
    with patch("selenium.webdriver.Chrome", return_value=driver), patch(
        "webdriver_manager.chrome.ChromeDriverManager"
    ) as manager, patch("moodlectl.cli.microsoft_auth._microsoft_password", return_value=None), patch(
        "moodlectl.cli.microsoft_auth.time.sleep"
    ), patch("moodlectl.cli.microsoft_auth.Config.load"), patch(
        "moodlectl.cli.microsoft_auth.MoodleClient.from_config", return_value=client
    ):
        manager.return_value.install.return_value = "chromedriver"
        microsoft_login(username="teacher@example.com", timeout=30)
    account.click.assert_called_once()
    yes.click.assert_called_once()
    client.get_courses.assert_called_once()
    driver.quit.assert_called_once()


def test_microsoft_reconnection_retries_only_once():
    with patch("moodlectl.cli.microsoft_auth._microsoft_login_once", side_effect=[RuntimeError("transfer failed"), None]) as attempt:
        microsoft_login(username="teacher@example.com", timeout=30)
    assert attempt.call_count == 2


@pytest.mark.parametrize("platform,parts", [
    ("win32", ("AppData", "Local", "moodlectl", "microsoft-browser")),
    ("darwin", ("Library", "Application Support", "moodlectl", "microsoft-browser")),
])
def test_platform_specific_profile_paths(tmp_path, monkeypatch, platform, parts):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with patch("moodlectl.cli.microsoft_auth.sys.platform", platform), patch(
        "moodlectl.cli.microsoft_auth.Path.home", return_value=tmp_path
    ):
        assert _browser_profile() == tmp_path.joinpath(*parts)


def test_windows_credential_store_selection():
    store = type("NativeStore", (), {"__module__": "keyring.backends.Windows"})()
    with patch("moodlectl.cli.microsoft_auth.sys.platform", "win32"), patch(
        "keyring.get_keyring", return_value=store
    ):
        assert _credential_store() is store


def test_macos_uses_keychain_despite_global_keyring_override():
    # The backend can be imported on other platforms, but only constructed on
    # macOS. Mock construction so CI can exercise this path on Linux too.
    with patch("moodlectl.cli.microsoft_auth.sys.platform", "darwin"), patch(
        "keyring.backends.macOS.Keyring"
    ) as keychain, patch("keyring.get_keyring") as configured_backend:
        assert _credential_store() is keychain.return_value
    configured_backend.assert_not_called()


def test_plaintext_credential_store_is_rejected():
    store = type("PlaintextStore", (), {"__module__": "keyrings.alt.file"})()
    with patch("moodlectl.cli.microsoft_auth.sys.platform", "win32"), patch(
        "keyring.get_keyring", return_value=store
    ), pytest.raises(RuntimeError, match="Native credential store unavailable"):
        _credential_store()


def test_credential_prompt_does_not_write_or_echo_password(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOODLE_BASE_URL", "https://moodle.example.com")
    store = Mock()
    with patch("moodlectl.cli.microsoft_auth._credential_store", return_value=store):
        result = CliRunner().invoke(app, ["auth", "microsoft-credentials", "--username", "teacher@example.com"], input="fake-vault-password\nfake-vault-password\n")
    assert result.exit_code == 0, result.output
    assert "fake-vault-password" not in result.output
    assert "fake-vault-password" not in (tmp_path / ".env").read_text()
    store.set_password.assert_called_once_with("moodlectl:microsoft:https://moodle.example.com", "teacher@example.com", "fake-vault-password")


def test_keychain_save_failure_keeps_config_and_password_private(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOODLE_BASE_URL", "https://moodle.example.com")
    env_path = tmp_path / ".env"
    env_path.write_text("EXISTING_CONFIG=keep\n")
    store = Mock()
    store.set_password.side_effect = RuntimeError("backend exposed fake-vault-password")
    with patch("moodlectl.cli.microsoft_auth._credential_store", return_value=store):
        result = CliRunner().invoke(app, ["auth", "microsoft-credentials", "--username", "teacher@example.com"], input="fake-vault-password\nfake-vault-password\n")
    assert result.exit_code == 1
    assert "Unlock macOS Keychain" in result.output
    assert "fake-vault-password" not in result.output
    assert env_path.read_text() == "EXISTING_CONFIG=keep\n"


def test_missing_storage_dependency_has_install_hint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOODLE_BASE_URL", "https://moodle.example.com")
    with patch.dict("sys.modules", {"keyring": None}):
        result = CliRunner().invoke(app, ["auth", "microsoft-credentials", "--username", "teacher@example.com"])
    assert result.exit_code == 1
    assert 'pip install "moodlectl[browser]"' in " ".join(result.output.split())
    assert not (tmp_path / ".env").exists()


def test_auto_login_runs_before_command_and_stops_on_failure(monkeypatch):
    monkeypatch.delenv("MOODLE_AUTO_LOGIN", raising=False)
    client = Mock()
    client.get_courses.return_value = []
    with patch("moodlectl.cli.auth.login") as login, patch(
        "moodlectl.cli.courses.MoodleClient.from_config", return_value=client
    ), patch("moodlectl.cli.courses.Config.load"):
        result = CliRunner().invoke(app, ["--auto-login", "courses", "list"])
    assert result.exit_code == 0, result.output
    login.assert_called_once()
    client.get_courses.assert_called_once()
    with patch("moodlectl.cli.auth.login", side_effect=typer.Exit(1)), patch(
        "moodlectl.cli.courses.MoodleClient.from_config"
    ) as dispatch:
        result = CliRunner().invoke(app, ["--auto-login", "courses", "list"])
    assert result.exit_code == 1
    dispatch.assert_not_called()


def test_auto_login_does_not_recurse_for_auth_commands(monkeypatch):
    monkeypatch.setenv("MOODLE_AUTO_LOGIN", "true")
    with patch("moodlectl.cli.auth.login") as login:
        result = CliRunner().invoke(app, ["--auto-login", "auth", "--help"])
    assert result.exit_code == 0
    login.assert_not_called()

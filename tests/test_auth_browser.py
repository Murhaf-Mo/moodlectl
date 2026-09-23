from unittest.mock import Mock, PropertyMock, patch

from dotenv import dotenv_values

from moodlectl.cli.auth import _extract_via_selenium


def test_sso_callback_is_skipped_and_live_session_key_is_saved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    driver = Mock()
    type(driver).current_url = PropertyMock(side_effect=[
        'https://moodle.example.com/auth/oidc/',
        'https://moodle.example.com/my/',
    ])
    driver.page_source = '<html>No embedded JSON session key</html>'
    driver.get_cookies.return_value = [
        {'name': 'MoodleSession', 'value': 'session', 'domain': 'moodle.example.com', 'path': '/'},
        {'name': 'Affinity', 'value': 'server', 'domain': 'moodle.example.com', 'path': '/'},
    ]

    def execute(script):
        if script == 'return M.cfg.sesskey':
            return 'live-key'
        if script == 'return navigator.userAgent':
            return 'Browser UA'
        return True

    driver.execute_script.side_effect = execute
    with patch('selenium.webdriver.Chrome', return_value=driver), \
            patch('webdriver_manager.chrome.ChromeDriverManager') as manager, \
            patch('moodlectl.cli.auth.time.sleep'):
        manager.return_value.install.return_value = 'chromedriver'
        assert _extract_via_selenium('https://moodle.example.com') == ('session', 'live-key')
    values = dotenv_values(tmp_path / '.env')
    assert values['MOODLE_BROWSER_USER_AGENT'] == 'Browser UA'
    assert 'Affinity' in values['MOODLE_BROWSER_COOKIES']
    driver.quit.assert_called_once()

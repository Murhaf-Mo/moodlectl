from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from moodlectl.client import MoodleClient
from moodlectl.types import CourseId


@pytest.fixture(params=['overviewfiles_filemanager', 'overviewfiles'])
def image_client(tmp_path, request):
    client = MoodleClient('https://moodle.example.com', 'cookie', 'key')
    path = tmp_path / 'thumbnail.jpg'
    path.write_bytes(b'jpeg-content')
    soup = BeautifulSoup(f'''<form>
        <input name="{request.param}" value="123">
        <input name="fullname" value="Keep course name">
        <input name="visible" value="0">
        <textarea name="summary_editor[text]">Keep description</textarea>
    </form>''', 'html.parser')
    client._get_soup = Mock(return_value=soup)
    client._upload_to_draft = Mock()
    responses = [
        {'list': [{'filename': 'old.png', 'filepath': '/'}]},
        {'filepath': '/'},
        None,
        {'list': [{'filename': path.name, 'url': 'https://moodle.example.com/draftfile.php/image'}]},
    ]
    client._post_form = Mock(side_effect=[
        Mock(url='https://moodle.example.com/course/view.php?id=1', json=Mock(return_value=x))
        for x in responses
    ])
    client._session.get = Mock(return_value=Mock(content=path.read_bytes()))
    return client, path


def test_image_replacement_preserves_other_settings_and_verifies_bytes(image_client):
    client, path = image_client
    client.set_course_image(CourseId(1), str(path))
    submitted = client._post_form.call_args_list[2].args[1]
    assert submitted['fullname'] == 'Keep course name'
    assert submitted['visible'] == '0'
    assert submitted['summary_editor[text]'] == 'Keep description'
    assert submitted.get('overviewfiles_filemanager', submitted.get('overviewfiles')) == '123'
    assert client._post_form.call_args_list[1].args[1]['action'] == 'delete'
    client._session.get.assert_called_once()


def test_upload_failure_does_not_save_live_course(image_client):
    client, path = image_client
    client._upload_to_draft.side_effect = RuntimeError('Upload rejected')
    with pytest.raises(RuntimeError, match='Upload rejected'):
        client.set_course_image(CourseId(1), str(path))
    assert all('course/edit.php' not in call.args[0] for call in client._post_form.call_args_list)


def test_missing_file_never_contacts_moodle(image_client):
    client, path = image_client
    with pytest.raises(ValueError, match='does not exist'):
        client.set_course_image(CourseId(1), str(path.parent / 'missing.jpg'))
    client._get_soup.assert_not_called()


def test_saved_byte_mismatch_is_reported(image_client):
    client, path = image_client
    client._session.get.return_value.content = b'wrong-image'
    with pytest.raises(RuntimeError, match='contents could not be verified'):
        client.set_course_image(CourseId(1), str(path))


def test_session_cookie_is_scoped_to_moodle_host():
    client = MoodleClient('https://moodle.example.com', 'old', 'key')
    client._session.cookies.set('MoodleSession', 'new', domain='moodle.example.com', path='/')
    cookies = list(client._session.cookies)
    assert len(cookies) == 1
    assert cookies[0].value == 'new'


def test_browser_identity_and_site_affinity_are_preserved():
    import json

    from moodlectl.config import Config

    config = Config('https://moodle.example.com', 'current', 'key', '',
                    browser_user_agent='Browser UA', browser_cookies=json.dumps([
                        {'name': 'MoodleSession', 'value': 'stale', 'domain': 'moodle.example.com'},
                        {'name': 'Affinity', 'value': 'server1', 'domain': 'moodle.example.com'},
                        {'name': 'SSO', 'value': 'private', 'domain': 'identity.example.org'},
                    ]))
    client = MoodleClient.from_config(config)
    assert client._session.headers['User-Agent'] == 'Browser UA'
    assert client._session.cookies.get_dict() == {'MoodleSession': 'current', 'Affinity': 'server1'}


def test_missing_filemanager_does_not_upload(image_client):
    client, path = image_client
    client._get_soup.return_value = BeautifulSoup('<form><input name="id" value="1"></form>', 'html.parser')
    with pytest.raises(RuntimeError, match='no overview image'):
        client.set_course_image(CourseId(1), str(path))
    client._upload_to_draft.assert_not_called()
    client._post_form.assert_not_called()


def test_config_reads_working_directory_env(tmp_path):
    import os
    import subprocess
    import sys

    (tmp_path / '.env').write_text('MOODLE_BASE_URL=https://workspace.example.com\n'
                                  'MOODLE_SESSION=workspace-session\nMOODLE_SESSKEY=key\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith('MOODLE_')}
    result = subprocess.run([sys.executable, '-c',
                             ('from moodlectl.config import Config; '
                             'c=Config.load(); '
                             'assert c.base_url=="https://workspace.example.com"; '
                             'assert c.moodle_session=="workspace-session"')],
                            cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from moodlectl.client import MoodleClient
from moodlectl.features.content import replace_resource_file
from moodlectl.types import Cmid, CourseId


@pytest.fixture
def resource(tmp_path):
    client = MoodleClient('https://moodle.example.com', 'cookie', 'key')
    path = tmp_path / 'syllabus.docx'
    path.write_bytes(b'new-document')
    client._get_soup = Mock(return_value=BeautifulSoup('''<form>
        <input name="modulename" value="resource"><input name="files" value="123">
        <input name="name" value="Keep title"><input name="visible" value="0">
        <textarea name="introeditor[text]">Keep description</textarea>
        </form>''', 'html.parser'))
    client._upload_to_draft = Mock()
    client.get_module_form = Mock(return_value={'files': '456'})
    client._post_form = Mock(side_effect=[Mock(
        url='https://moodle.example.com/course/view.php?id=1', json=Mock(return_value=result))
        for result in [
            {'list': [{'filename': 'original.docx', 'filepath': '/'}]},
            {'filepath': '/'}, {},
            {'list': [{'filename': path.name, 'url': 'https://moodle.example.com/draftfile.php/file'}]},
        ]])
    client._session.get = Mock(return_value=Mock(content=path.read_bytes()))
    return client, path


def test_preserves_settings_and_verifies_bytes(resource):
    client, path = resource
    client.replace_resource_file(Cmid(1), str(path))
    submitted = client._post_form.call_args_list[2].args[1]
    assert submitted['name'] == 'Keep title'
    assert submitted['visible'] == '0'
    assert submitted['introeditor[text]'] == 'Keep description'
    assert submitted['files'] == '123'
    client._session.get.assert_called_once()


def test_upload_failure_never_saves(resource):
    client, path = resource
    client._upload_to_draft.side_effect = RuntimeError('Upload failed')
    with pytest.raises(RuntimeError, match='Upload failed'):
        client.replace_resource_file(Cmid(1), str(path))
    assert all('modedit.php' not in call.args[0] for call in client._post_form.call_args_list)


def test_multi_file_resource_refused_before_deletion(resource):
    client, path = resource
    client._post_form.side_effect = None
    client._post_form.return_value.json.return_value = {'list': [{'filename': 'a'}, {'filename': 'b'}]}
    with pytest.raises(ValueError, match='exactly one'):
        client.replace_resource_file(Cmid(1), str(path))
    assert client._post_form.call_count == 1
    client._upload_to_draft.assert_not_called()


def test_missing_file_never_contacts_moodle(resource):
    client, path = resource
    with pytest.raises(ValueError, match='does not exist'):
        client.replace_resource_file(Cmid(1), str(path.parent / 'missing.docx'))
    client._get_soup.assert_not_called()


def test_mismatched_saved_bytes_reported(resource):
    client, path = resource
    client._session.get.return_value.content = b'wrong'
    with pytest.raises(RuntimeError, match='contents could not be verified'):
        client.replace_resource_file(Cmid(1), str(path))


def test_wrong_course_refused(resource):
    client, path = resource
    client.get_course_sections = Mock(return_value=[])
    client.replace_resource_file = Mock()
    with pytest.raises(ValueError, match='does not contain'):
        replace_resource_file(client, CourseId(2), Cmid(1), str(path))
    client.replace_resource_file.assert_not_called()

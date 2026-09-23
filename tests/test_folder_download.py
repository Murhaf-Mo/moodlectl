from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from moodlectl.client import MoodleClient


def client_for(html):
    client = object.__new__(MoodleClient)
    client.base_url = 'https://moodle.example'
    client._get_soup = Mock(return_value=BeautifulSoup(html, 'html.parser'))
    client.download_file = Mock()
    return client


def test_folder_download_deduplicates_and_preserves_subfolders(tmp_path):
    url = '/pluginfile.php/12/mod_folder/content/0/Unit%201/file.pdf'
    client = client_for(f'<a href="{url}?forcedownload=1">file</a><a href="{url}">same</a><a href="https://other.example{url}">external</a>')
    result = client.download_folder(123, tmp_path)
    assert result == [str(tmp_path / 'Unit 1' / 'file.pdf')]
    client.download_file.assert_called_once()


@pytest.mark.parametrize('path', ['../escape.pdf', '%2e%2e/escape.pdf', 'C:%5cescape.pdf'])
def test_folder_rejects_unsafe_paths(tmp_path, path):
    client = client_for(f'<a href="/pluginfile.php/12/mod_folder/content/0/{path}">file</a>')
    with pytest.raises(ValueError):
        client.download_folder(123, tmp_path)
    client.download_file.assert_not_called()


def test_folder_without_attachments_fails(tmp_path):
    client = client_for('<p>Please log in</p>')
    with pytest.raises(RuntimeError):
        client.download_folder(123, tmp_path)

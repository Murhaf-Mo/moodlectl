import pytest
from moodlectl.client.base import MoodleClientBase


@pytest.fixture
def mock_client(mocker):
    client = MoodleClientBase.__new__(MoodleClientBase)
    client.base_url = "https://mylms.cck.edu.kw"
    client.sesskey = "test_sesskey"
    client.ajax = mocker.MagicMock()
    return client

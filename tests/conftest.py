import pytest
from pytest_mock import MockerFixture

from moodlectl.client.base import MoodleClientBase


@pytest.fixture
def mock_client(mocker: MockerFixture) -> MoodleClientBase:
    client = MoodleClientBase.__new__(MoodleClientBase)
    client.base_url = "https://moodle.example.com"
    client.sesskey = "test_sesskey"
    client.ajax = mocker.MagicMock()  # type: ignore[method-assign]
    return client

import pytest
from pytest_mock import MockerFixture

from moodlectl.client.base import MoodleClientBase


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "demo: end-to-end test that hits the live school.moodledemo.net "
        "instance. Skipped by default; run with `pytest -m demo`.",
    )


@pytest.fixture
def mock_client(mocker: MockerFixture) -> MoodleClientBase:
    client = MoodleClientBase.__new__(MoodleClientBase)
    client.base_url = "https://moodle.example.com"
    client.sesskey = "test_sesskey"
    client.ajax = mocker.MagicMock()  # type: ignore[method-assign]
    return client

from moodlectl.features.courses import _normalise  # type: ignore[reportPrivateUsage]
from moodlectl.types import Participant, UserId


def test_normalise_user() -> None:
    raw: Participant = {
        "id": UserId(42),
        "fullname": "Ali Hassan",
        "email": "ali@example.com",
        "roles": "student",
        "lastaccess": "3 days ago",
        "status": "Active",
    }
    result = _normalise(raw)
    assert result["id"] == 42
    assert result["fullname"] == "Ali Hassan"
    assert result["roles"] == "student"


def test_normalise_user_no_roles() -> None:
    raw: Participant = {
        "id": UserId(1),
        "fullname": "Test",
        "email": "",
        "roles": "",
        "lastaccess": "",
        "status": "",
    }
    result = _normalise(raw)
    assert result["roles"] == "—"

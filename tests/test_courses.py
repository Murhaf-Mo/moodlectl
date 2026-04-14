from moodlectl.features.courses import _normalise


def test_normalise_user():
    raw = {
        "id": 42,
        "fullname": "Ali Hassan",
        "email": "ali@example.com",
        "roles": [{"shortname": "student"}],
        "lastaccess": 1700000000,
    }
    result = _normalise(raw)
    assert result["id"] == 42
    assert result["fullname"] == "Ali Hassan"
    assert result["roles"] == "student"


def test_normalise_user_no_roles():
    raw = {"id": 1, "fullname": "Test", "email": "", "roles": [], "lastaccess": 0}
    result = _normalise(raw)
    assert result["roles"] == "—"

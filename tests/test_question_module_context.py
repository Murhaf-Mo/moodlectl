from unittest.mock import Mock

from moodlectl.client import MoodleClient


def test_categories_use_module_context_when_supplied():
    client = object.__new__(MoodleClient)
    client.base_url = 'https://moodle.example'
    client._session = Mock()
    response = client._session.get.return_value
    response.url = 'https://moodle.example/question/bank/managecategories/category.php?cmid=12'
    response.text = '<ul><li><a href="edit.php?cat=23%2C45">Test (10)</a></li></ul>'
    assert client.find_question_category(905, 'Test', cmid=12) == (23, 45)
    assert client._session.get.call_args.kwargs['params'] == {'cmid': 12}
    assert client.list_question_categories(905, cmid=12)[0]['count'] == 10
    assert client._session.get.call_args.kwargs['params'] == {'cmid': 12}


def test_categories_keep_legacy_course_route():
    client = object.__new__(MoodleClient)
    client.base_url = 'https://moodle.example'
    client._session = Mock()
    response = client._session.get.return_value
    response.url = 'https://moodle.example/question/bank/managecategories/category.php?courseid=905'
    response.text = ''
    assert client.list_question_categories(905) == []
    assert client._session.get.call_args.kwargs['params'] == {'courseid': 905}

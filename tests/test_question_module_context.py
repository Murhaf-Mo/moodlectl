from unittest.mock import Mock
import pytest

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


@pytest.mark.parametrize('cmid,route', [(12, {'cmid': 12}), (None, {'courseid': 905})])
def test_export_preserves_question_bank_context(cmid, route):
    client = object.__new__(MoodleClient)
    client.base_url = 'https://moodle.example'
    client.sesskey = 'test-session'
    client._session = Mock()
    listing = Mock(url='https://moodle.example/question/edit.php', text='<tr class="r0"><td data-questionid="123"></td></tr>')
    export = Mock(status_code=200, url='https://moodle.example/question/bank/exporttoxml/exportone.php', text='<quiz><question type="truefalse"><name><text>Test</text></name></question></quiz>')
    client._session.get.side_effect = [listing, export]
    result = client.export_question_bank(905, 23, 45, 'Test', cmid=cmid)
    assert '<question type="truefalse">' in result
    calls = client._session.get.call_args_list
    assert calls[0].kwargs['params'] == {**route, 'cat': '23,45', 'qperpage': 1000}
    assert calls[1].kwargs['params'] == {**route, 'id': 123, 'sesskey': 'test-session'}

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from bs4 import BeautifulSoup
from typer.testing import CliRunner

from moodlectl.cli.main import app
from moodlectl.features import question_review as review


def attempt(aid=1, qid=11, slot=1, mark=0):
    return {'id': aid, 'student': 'Example Student', 'user_id': '3', 'before': float(mark), 'max_grade': 1.0,
            'questions': [{'id': qid, 'slot': slot, 'mark': float(mark), 'maxmark': 1.,
                           'text_hash': review._hash(BeautifulSoup('<div class="qtext">Stem</div>', 'html.parser').div),
                           'response_hash': 'response-fingerprint'}]}


def inputs():
    return ({'schema_version': 1, 'review_id': 'r1', 'source': {'base_url': 'https://moodle.example', 'quiz_id': 7},
             'questions': [{'id': 11}, {'id': 22}]},
            {'schema_version': 1, 'review_id': 'r1', 'base_url': 'https://moodle.example',
             'complete': True, 'selected_question_ids': [11], 'decisions': {'11': 'full_credit', '22': 'keep'}})


def test_plan_matches_identity_not_random_slot():
    client = Mock(base_url='https://moodle.example')
    artifact, selection = inputs()
    # Same quiz position, different random questions: only ID 11 earns credit.
    with patch.object(review, 'attempt_snapshot', return_value=[attempt(), attempt(aid=2, qid=22)]):
        plan = review.make_credit_plan(client, 7, artifact, selection)
    assert [a['after'] for a in plan['attempts']] == [1., 0.]
    assert plan['retire_questions'] is False
    client.ajax.assert_not_called()
    client._session.post.assert_not_called()


@pytest.mark.parametrize('change', ['review', 'site', 'quiz', 'incomplete', 'id'])
def test_mismatched_selection_is_rejected_before_access(change):
    artifact, selection = inputs()
    if change == 'review':
        selection['review_id'] = 'other'
    if change == 'site':
        selection['base_url'] = 'https://other.example'
    if change == 'quiz':
        artifact['source']['quiz_id'] = 99
    if change == 'incomplete':
        selection['complete'] = False
    if change == 'id':
        selection['selected_question_ids'] = [999]
    client = Mock(base_url='https://moodle.example')
    with patch.object(review, 'attempt_snapshot') as snapshot, pytest.raises(review.ReviewError):
        review.make_credit_plan(client, 7, artifact, selection)
    snapshot.assert_not_called()


def test_report_pagination_does_not_silently_drop_students():
    client = Mock()
    client.get_quiz_attempts.side_effect = [[{'attempt_id': '1'}], [{'attempt_id': '2'}], []]
    assert len(review._all_attempts(client, 7)) == 2
    assert [c.kwargs['page'] for c in client.get_quiz_attempts.call_args_list] == [0, 1, 2]
    client.get_quiz_attempts.side_effect = [[{'attempt_id': '1'}], [{'attempt_id': '1'}]]
    with pytest.raises(review.ReviewError, match='pagination'):
        review._all_attempts(client, 7)


def test_unfinished_attempts_block_grade_plans():
    client = Mock()
    with patch.object(review, '_all_attempts', return_value=[{'state': 'In progress'}]), pytest.raises(review.ReviewError, match='unfinished'):
        review.attempt_snapshot(client, 7)


@pytest.mark.parametrize('field,value', [('response_hash', 'new-answer'), ('text_hash', 'new-text'), ('mark', .5), ('id', 99)])
def test_stale_plan_stops_before_any_write(tmp_path, field, value):
    before = attempt()
    live = deepcopy(before)
    live['questions'][0][field] = value
    plan = {'schema_version': 1, 'policy': 'full_credit', 'retire_questions': False,
            'base_url': 'https://moodle.example', 'quiz_id': 7, 'selected_question_ids': [11], 'attempts': [before]}
    client = Mock(base_url='https://moodle.example')
    with patch.object(review, 'attempt_snapshot', return_value=[live]), pytest.raises(review.ReviewError, match='changed'):
        review.apply_credit_plan(client, plan, tmp_path / 'journal.jsonl')
    client._session.post.assert_not_called()
    assert not (tmp_path / 'journal.jsonl').exists()


def test_apply_preserves_answers_and_comments_and_verifies_report(tmp_path):
    client = Mock(base_url='https://moodle.example')
    before, after = attempt(), attempt(mark=1)
    plan = {'schema_version': 1, 'plan_id': 'p1', 'policy': 'full_credit', 'retire_questions': False,
            'base_url': client.base_url, 'quiz_id': 7, 'selected_question_ids': [11], 'attempts': [before]}
    form = BeautifulSoup('''<form action="/mod/quiz/comment.php"><div class="qtext">Stem</div>
      <input name="q1:1_:sequencecheck" value="3"><input name="q1:1_answer" type="radio" checked value="0" disabled>
      <input name="q1:1_-mark" value="0"><input name="q1:1_-maxmark" value="1">
      <input name="sesskey" value="fake-session"><textarea name="q1:1_-comment">Existing comment</textarea>
      <input name="answer" value="Student response" readonly><input name="cancel" type="submit" value="Cancel"><input name="submit" type="submit" value="Save"></form>''', 'html.parser')
    saved = BeautifulSoup('<div class="que"><div class="grade">Mark 1.00 out of 1.00</div></div>', 'html.parser')
    journal = tmp_path / 'journal.jsonl'
    with patch.object(review, 'attempt_snapshot', side_effect=[[before], [after]]), patch.object(review, '_get', side_effect=[form, saved]):
        assert review.apply_credit_plan(client, plan, journal) == 1
    data = client._session.post.call_args.kwargs['data']
    assert data['q1:1_-mark'] == '1.0'
    assert data['q1:1_-comment'].startswith('Existing comment')
    assert 'q1:1_answer' not in data
    assert 'answer' not in data and 'cancel' not in data
    assert 'question version' in data['q1:1_-comment'].lower()
    records = [json.loads(line) for line in journal.read_text().splitlines()]
    assert [r['state'] for r in records] == ['pending', 'verified', 'complete']
    with pytest.raises(review.ReviewError, match='Journal exists'):
        review.apply_credit_plan(client, plan, journal)


def test_interrupted_save_keeps_pending_journal_and_cannot_replay(tmp_path):
    client = Mock(base_url='https://moodle.example')
    client._session.post.side_effect = TimeoutError('interrupted')
    before = attempt()
    plan = {'schema_version': 1, 'plan_id': 'p', 'policy': 'full_credit', 'retire_questions': False,
            'base_url': client.base_url, 'quiz_id': 7, 'selected_question_ids': [11], 'attempts': [before]}
    form = BeautifulSoup('<form action="/mod/quiz/comment.php"><div class="qtext">Stem</div><input name="q_-mark" value="0"><textarea name="q_-comment"></textarea></form>', 'html.parser')
    journal = tmp_path / 'log'
    with patch.object(review, 'attempt_snapshot', return_value=[before]), patch.object(review, '_get', return_value=form), pytest.raises(TimeoutError):
        review.apply_credit_plan(client, plan, journal)
    assert json.loads(journal.read_text())['state'] == 'pending'
    with pytest.raises(review.ReviewError, match='Journal exists'):
        review.apply_credit_plan(client, plan, journal)


def test_offline_markup_has_no_active_content_or_external_media():
    client = Mock(base_url='https://moodle.example')
    node = BeautifulSoup('''<div class="que"><div class="qtext" onclick="bad()"><p dir="rtl">سؤال</p>
      <script>bad()</script><img src="https://other.example/track" onerror="bad()" alt="code">
      <a href="javascript:bad()">Link text</a><iframe src="https://other.example/"></iframe></div>
      <div class="ablock"><input type="radio" checked>Choice</div></div>''', 'html.parser').div
    html, warnings = review._content(node, client)
    assert all(x not in html for x in ('onclick', 'onerror', '<script', '<iframe', 'https://other', 'javascript:', '<input'))
    assert 'dir="rtl"' in html and 'Choice' in html and warnings
    client._session.get.assert_not_called()


def test_images_are_embedded_without_session_links():
    client = Mock(base_url='https://moodle.example')
    client._session.get.return_value = Mock(status_code=200, content=b'png-image', headers={'Content-Type': 'image/png'})
    node = BeautifulSoup('<div><div class="qtext"><img src="/pluginfile.php/image.png" alt="code"></div></div>', 'html.parser').div
    html, warnings = review._content(node, client)
    assert 'data:image/png;base64,' in html and 'pluginfile.php' not in html and not warnings


def test_saved_page_cannot_break_out_of_json_and_contains_no_names(tmp_path):
    artifact = {'review_id': 'id', 'questions': [{'id': 1, 'name': '</script><script>bad()</script>', 'html': '<p>Stem</p>'}]}
    path = review.save_review(artifact, tmp_path)
    doc = BeautifulSoup(path.read_text(), 'html.parser')
    assert json.loads(doc.select_one('#review-data').string) == artifact
    assert 'bad()' not in ''.join(s.get_text() for s in doc.select('script:not([type="application/json"])'))
    with pytest.raises(review.ReviewError, match='already exist'):
        review.save_review(artifact, tmp_path)


def test_skill_discovery_works_without_login_even_with_auto_login(monkeypatch):
    monkeypatch.setenv('MOODLE_AUTO_LOGIN', 'true')
    runner = CliRunner()
    with patch('moodlectl.cli.auth.login') as login:
        listed = runner.invoke(app, ['skills', 'list'])
        shown = runner.invoke(app, ['skills', 'show', 'moodle-quiz-question-remediation'])
        located = runner.invoke(app, ['skills', 'path', 'moodle-quiz-question-remediation'])
    assert listed.exit_code == shown.exit_code == located.exit_code == 0
    assert 'moodle-quiz-question-remediation' in listed.output
    assert (Path(located.output.strip()) / 'SKILL.md').read_text() == shown.output
    login.assert_not_called()
    assert runner.invoke(app, ['skills', 'show', '../../config']).exit_code != 0


def test_course_scope_does_not_assume_a_quiz():
    client = Mock(base_url='https://moodle.example')
    with pytest.raises(review.ReviewError, match='--course'):
        review.collect_review(client, 'course')
    client.get_courses.assert_not_called()


def test_attempted_review_uses_blank_preview_not_student_essay():
    client = Mock(base_url='https://moodle.example')
    student_page = BeautifulSoup('''<div class="que" id="question-1-1"><div class="editquestion"><a href="/question/bank/editquestion/question.php?id=11">Edit</a></div><div class="qtext">Essay stem</div><div class="ablock"><div class="answer">PRIVATE STUDENT ESSAY</div></div></div>''', 'html.parser')
    blank = BeautifulSoup('<div class="que"><div class="qtext">Essay stem</div><div class="ablock"><textarea></textarea></div></div>', 'html.parser')
    with patch.object(review, 'attempt_snapshot', return_value=[attempt()]), patch.object(review, '_get', side_effect=[student_page, BeautifulSoup('<h1>Quiz</h1>', 'html.parser'), blank]) as get:
        artifact = review.collect_review(client, 'attempted', quiz=7, view='offline')
    assert 'PRIVATE STUDENT ESSAY' not in json.dumps(artifact)
    assert 'preview.php?id=11' in get.call_args.args[1]
    assert artifact['questions'][0]['attempt_count'] == 1


def test_matching_choices_are_preserved_offline():
    node = BeautifulSoup('<div><div class="qtext">Match the words</div><div class="ablock"><select><option>Choose…</option><option>TCP</option><option>UDP</option></select></div></div>', 'html.parser').div
    html, _ = review._content(node, Mock(base_url='https://moodle.example'))
    assert 'TCP' in html and 'UDP' in html and '<select' not in html


def test_full_credit_does_not_remove_bonus_marks():
    artifact, selection = inputs()
    with patch.object(review, 'attempt_snapshot', return_value=[attempt(mark=1.5)]):
        plan = review.make_credit_plan(Mock(base_url='https://moodle.example'), 7, artifact, selection)
    assert plan['attempts'][0]['after'] == 1.5


@pytest.mark.parametrize('decisions', [{}, {'11': 'full_credit'}, {'11': 'keep', '22': 'keep'}, {'11': 'full_credit', '22': 'unknown'}])
def test_complete_flag_alone_cannot_fake_a_finished_review(decisions):
    artifact, selection = inputs()
    selection['decisions'] = decisions
    with patch.object(review, 'attempt_snapshot') as snapshot, pytest.raises(review.ReviewError):
        review.make_credit_plan(Mock(base_url='https://moodle.example'), 7, artifact, selection)
    snapshot.assert_not_called()


def test_all_attempts_uses_settings_form_and_clears_report_filters():
    from moodlectl.client import MoodleClient
    client = object.__new__(MoodleClient)
    client.base_url = 'https://moodle.example'
    client._session = Mock()
    # A real Moodle page has an edit-mode form before its report settings form.
    settings = '''<form action="/editmode.php"><input name="setmode" value="1"></form>
    <form><input name="id" value="7"><input name="mode" value="overview"><input name="_qf__quiz_overview_settings_form" value="1">
    <select name="attempts"><option value="enrolled_with" selected>Enrolled users</option><option value="all_with">All users who have a quiz attempt</option></select>
    <input name="onlygraded" type="checkbox" value="1" checked><input name="onlyregraded" type="checkbox" value="1" checked>
    <input name="statefinished" type="checkbox" value="1" checked><input name="stateinprogress" type="checkbox" value="1">
    <input name="submitbutton" type="submit" value="Show report"></form>'''
    client._session.get.return_value = Mock(url=client.base_url + '/mod/quiz/report.php', status_code=200, text=settings)
    client._session.post.return_value = Mock(url=client.base_url + '/mod/quiz/report.php', text='<table id="attempts"><thead><tr><th>Name</th><th>Status</th><th>Grade/5.00</th><th>Started</th></tr></thead><tbody><tr><td>Example Student <a href="review.php?attempt=99">Review attempt</a></td><td>Finished</td><td>4.00</td><td>Today</td></tr></tbody></table>')
    rows = client.get_quiz_attempts(7, page=2, all_attempts=True)
    data = client._session.post.call_args.kwargs['data']
    assert 'setmode' not in data
    assert data['attempts'] == 'all_with' and data['onlygraded'] == data['onlyregraded'] == '0'
    assert data['group'] == '0' and data['stateinprogress'] == '1'
    assert rows[0]['attempt_id'] == '99' and rows[0]['max_grade'] == '5.00'
    assert 'page=2' in client._session.post.call_args.args[0]


@pytest.mark.parametrize('response_html', ['<input type="text" name="answer" value="42" readonly>', '<div class="answer">An essay answer</div>', '<div class="answer"><a href="/pluginfile.php/attachment.pdf">Attachment</a></div>'])
def test_response_fingerprint_covers_text_inputs_essays_and_attachments(response_html):
    client = Mock()
    report = [{'attempt_id': '1', 'state': 'Finished', 'max_grade': '1.00', 'grade': '0.00', 'fullname': 'Student'}]
    def page(response):
        return BeautifulSoup('<div class="que" id="question-1-1"><div class="editquestion"><a href="/question.php?id=11">Edit</a></div><div class="grade">Mark 0.00 out of 1.00</div><div class="formulation"><div class="qtext">Stem</div><div class="ablock">'+response+'</div></div></div>', 'html.parser')
    with patch.object(review, '_all_attempts', return_value=report), patch.object(review, '_get', side_effect=[page(response_html), page('Different response')]):
        original = review.attempt_snapshot(client, 7)
        changed = review.attempt_snapshot(client, 7)
    assert original[0]['questions'][0]['response_hash'] != changed[0]['questions'][0]['response_hash']


def test_generic_flags_are_not_grading_authorization():
    artifact, selection = inputs()
    artifact['schema_version'] = 2
    selection.update(schema_version=2, intent='review', decisions={'11':'flag','22':'keep'})
    client = Mock(base_url='https://moodle.example')
    with patch.object(review, 'attempt_snapshot') as snapshot, pytest.raises(review.ReviewError, match='review flags'):
        review.make_credit_plan(client, 7, artifact, selection)
    snapshot.assert_not_called()
    with patch.object(review, 'attempt_snapshot', return_value=[attempt()]):
        plan = review.make_credit_plan(client, 7, artifact, selection, action='full-credit')
    assert plan['attempts'][0]['after'] == 1.


def test_moodle_view_exports_links_without_rendering_or_fetching_content():
    client = Mock(base_url='https://moodle.example')
    setup = BeautifulSoup('<h1>Quiz 2</h1><a href="https://moodle.example/question/bank/previewquestion/preview.php?id=11&amp;cmid=7&amp;sesskey=must-not-export">Preview</a>', 'html.parser')
    with patch.object(review, 'attempt_snapshot', return_value=[]), patch.object(review, '_get', return_value=setup) as get, patch.object(review, '_content') as content:
        artifact = review.collect_review(client, 'quiz', quiz=7)
    assert artifact['schema_version'] == 2
    assert artifact['source']['view'] == 'moodle' and artifact['source']['attempt_count'] == 0
    assert artifact['questions'][0]['html'] == ''
    assert artifact['questions'][0]['moodle_url'] == 'https://moodle.example/question/bank/previewquestion/preview.php?cmid=7&id=11'
    assert 'must-not-export' not in json.dumps(artifact)
    assert get.call_count == 1
    content.assert_not_called()

"""Offline question review and auditable full-credit corrections."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import uuid
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from moodlectl.types import Cmid, CourseId


class ReviewError(RuntimeError):
    """Unsupported or changed Moodle state; never guess at grading changes."""


def _origin(url):
    p = urlparse(url)
    return p.scheme, p.netloc


def _get(client, url, **params):
    url = urljoin(client.base_url + '/', url)
    if _origin(url) != _origin(client.base_url):
        raise ReviewError('Refusing a URL outside the configured Moodle site.')
    r = client._session.get(url, params=params or None, timeout=30)
    r.raise_for_status()
    if '/login/' in urlparse(r.url).path or _origin(r.url) != _origin(client.base_url):
        raise ReviewError('Session expired or redirected. Run moodlectl auth login.')
    return BeautifulSoup(r.text, 'html.parser')


def _qid(link):
    if link is None:
        raise ReviewError('Question identifier is missing.')
    values = parse_qs(urlparse(str(link.get('href', ''))).query)
    return int(values['id'][0]) if values.get('id') else None


def _number(text):
    try:
        value = float(text)
    except (ValueError, TypeError) as exc:
        raise ReviewError(f'Cannot interpret numeric mark: {text!r}') from exc
    if not math.isfinite(value):
        raise ReviewError('A mark is not finite.')
    return value


def _hash(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def _content(question, client):
    """Passive markup only; embed same-site raster images without credentials."""
    warnings = []
    content = BeautifulSoup('', 'html.parser')
    for selector in ('.qtext', '.ablock', '.rightanswer'):
        node = question.select_one(selector)
        if node:
            content.append(deepcopy(node))
    if not content.select_one('.qtext'):
        raise ReviewError('Question text is missing; cannot create a reliable card.')
    allowed = {'div', 'span', 'p', 'br', 'pre', 'code', 'b', 'strong', 'i', 'em', 'u',
               'sub', 'sup', 'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
               'blockquote', 'img', 'h3', 'h4', 'label', 'fieldset', 'legend', 'hr'}
    for tag in list(content.find_all(True)):
        if tag.parent is None:
            continue
        if tag.name == 'select':
            choices = ' / '.join(x.get_text(' ', strip=True) for x in tag.select('option'))
            tag.replace_with(content.new_string(choices))
            continue
        if tag.name in {'script', 'style', 'form', 'input', 'button', 'textarea',
                        'iframe', 'object', 'embed', 'svg', 'link', 'meta', 'audio', 'video'}:
            if tag.name in {'iframe', 'audio', 'video', 'object', 'embed'}:
                warnings.append('Embedded media is not available offline; check this question in Moodle.')
            tag.decompose()
            continue
        if tag.name not in allowed:
            tag.unwrap()
            continue
        attrs = {k: v for k, v in tag.attrs.items() if k in {'dir', 'lang', 'colspan', 'rowspan'}}
        if tag.name == 'img':
            alt = tag.get('alt', 'Question image')
            src = urljoin(client.base_url + '/', tag.get('src', ''))
            data = None
            if re.match(r'^data:image/(png|jpeg|gif|webp);base64,', src):
                data = src
            elif _origin(src) == _origin(client.base_url):
                response = client._session.get(src, timeout=30, allow_redirects=False)
                mime = response.headers.get('Content-Type', '').split(';')[0].lower()
                if response.status_code == 200 and mime in {'image/png', 'image/jpeg', 'image/gif', 'image/webp'} and len(response.content) <= 5_000_000:
                    data = f'data:{mime};base64,' + base64.b64encode(response.content).decode()
            if data:
                attrs.update(src=data, alt=alt)
            else:
                tag.replace_with(content.new_string(f'[Image unavailable: {alt}]'))
                warnings.append('An image could not be embedded. Check this question in Moodle.')
                continue
        tag.attrs = attrs
    return str(content), sorted(set(warnings))


def _listing(client, url):
    pending, seen, questions = [url], set(), {}
    while pending:
        page = pending.pop(0)
        if page in seen:
            continue
        seen.add(page)
        soup = _get(client, page)
        for row in soup.select('tr'):
            preview = row.select_one('a[href*="previewquestion/preview.php"], a[href*="question/preview.php"]')
            if not preview or not _qid(preview):
                continue
            qid = _qid(preview)
            questions[qid] = {'id': qid, 'name': preview.get_text(' ', strip=True) or f'Question {qid}',
                              'preview_url': urljoin(client.base_url, preview['href'])}
        for a in soup.select('.pagination a[href], .paging a[href]'):
            href = urljoin(client.base_url, a['href'])
            if urlparse(href).path == urlparse(page).path and href not in seen:
                pending.append(href)
    return questions


def _all_attempts(client, quiz):
    result, seen, page = [], set(), 0
    while True:
        rows = client.get_quiz_attempts(Cmid(quiz), page=page, all_attempts=True)
        if not rows:
            break
        ids = {int(a['attempt_id']) for a in rows if a['attempt_id']}
        if not ids or ids & seen:
            raise ReviewError('Attempt pagination repeated or lacks IDs; refusing an incomplete snapshot.')
        result.extend(rows)
        seen.update(ids)
        page += 1
        if page > 10000:
            raise ReviewError('Attempt pagination did not terminate.')
    return result


def attempt_snapshot(client, quiz):
    """All versions, marks and response fingerprints; grading requires finished attempts."""
    result = []
    for attempt in _all_attempts(client, quiz):
        if attempt['state'].strip().lower() != 'finished':
            raise ReviewError('A quiz attempt is unfinished. Finish or close attempts before grading corrections.')
        aid = int(attempt['attempt_id'])
        doc = _get(client, '/mod/quiz/review.php', attempt=aid, showall=1)
        questions = []
        for q in doc.select('.que'):
            qid = _qid(q.select_one('.editquestion a[href]'))
            grade = q.select_one('.grade')
            if not grade and 'description' in q.get('class', []):
                continue
            values = re.findall(r'-?\d+(?:\.\d+)?', grade.get_text(' ', strip=True) if grade else '')
            if not qid or len(values) != 2:
                raise ReviewError('An attempted question has an ungraded or unsupported mark/identifier.')
            mark, maximum = map(_number, values)
            formulation = q.select_one('.formulation')
            controls = [(x.get('name', ''), x.get('type', ''), x.get('value', ''),
                         x.has_attr('checked'), x.get_text())
                        for x in formulation.select('input, textarea, select option[selected]')
                        if not x.get('name', '').endswith('_:sequencecheck')]
            response_area = formulation.select_one('.ablock')
            response = {'controls': controls, 'rendered_text': response_area.get_text(' ', strip=True) if response_area else '',
                        'media': [(x.name, x.get('src', ''), x.get('href', '')) for x in response_area.select('[src], a[href]')] if response_area else []}
            questions.append({'id': qid, 'slot': int(q['id'].rsplit('-', 1)[1]), 'mark': mark,
                              'maxmark': maximum, 'text_hash': _hash(q.select_one('.qtext')),
                              'response_hash': _hash(json.dumps(response, sort_keys=True))})
        if not questions:
            raise ReviewError('No attempted questions found; check permissions or Moodle version.')
        total = sum(q['maxmark'] for q in questions)
        max_grade, before = _number(attempt['max_grade']), _number(attempt['grade'])
        if total <= 0 or abs(sum(q['mark'] for q in questions) / total * max_grade - before) > .011:
            raise ReviewError('Attempt total differs from the report grade; unsupported grading requires manual review.')
        result.append({'id': aid, 'student': attempt['fullname'], 'user_id': attempt.get('user_id', ''),
                       'before': before, 'max_grade': max_grade, 'questions': questions})
    return result


def collect_review(client, scope, *, quiz=None, courses=(), category=None, bank=None, view='moodle'):
    if view not in {'moodle', 'offline'}:
        raise ReviewError('Choose moodle or offline for --view.')
    if scope in {'quiz', 'attempted'} and not quiz:
        raise ReviewError('--quiz is required for quiz and attempted scopes.')
    if scope in {'course', 'category'} and not courses:
        raise ReviewError('--course is required for course and category scopes.')
    if scope == 'category' and (not category or len(courses) != 1):
        raise ReviewError('Category scope needs one --course and --category.')
    if scope not in {'quiz', 'attempted', 'category', 'bank', 'course', 'all'}:
        raise ReviewError('Unknown review scope.')
    if quiz and scope not in {'quiz', 'attempted'}:
        raise ReviewError('--quiz is only used by quiz and attempted scopes.')
    if category and scope != 'category':
        raise ReviewError('--category is only used by category scope.')
    if bank and scope not in {'category', 'bank'}:
        raise ReviewError('--bank is only used by bank/category scopes.')
    if scope == 'bank' and not bank:
        raise ReviewError('--bank is required for bank scope.')
    if courses and scope in {'quiz', 'attempted', 'all'}:
        raise ReviewError('Use --course with course/category scope; quiz/all scopes choose their own courses.')
    questions, attempts, quiz_title = {}, [], None
    if scope in {'quiz', 'attempted'}:
        attempts = attempt_snapshot(client, quiz)
        for attempt in attempts:
            doc = _get(client, '/mod/quiz/review.php', attempt=attempt['id'], showall=1)
            for q in doc.select('.que'):
                qid = _qid(q.select_one('.editquestion a'))
                if qid not in questions:
                    # Never export a student's rendered answer (essays may be readonly HTML).
                    # Fetch an exact-version teacher preview below, using attempts only for IDs/counts.
                    questions[qid] = {'id': qid, 'name': f'Question version {qid}',
                                      'preview_url': client.base_url + '/question/bank/previewquestion/preview.php?' + urlencode({'id': qid, 'cmid': quiz})}
        setup = _get(client, '/mod/quiz/edit.php', cmid=quiz)
        heading = setup.select_one('h1')
        quiz_title = heading.get_text(' ', strip=True) if heading else None
        listings = list(dict.fromkeys(urljoin(client.base_url, a['href']) for a in setup.select('a.mod_quiz_random_qbank_link[href]')))
        for url in listings:
            for qid, item in _listing(client, url).items():
                if scope == 'quiz' or qid in questions:
                    questions[qid] = {**item, **questions.get(qid, {}), 'name': item['name']}
        if scope == 'quiz':
            for a in setup.select('a[href*="preview.php"]'):
                qid = _qid(a)
                if qid:
                    questions.setdefault(qid, {'id': qid, 'name': a.get('title') or f'Question version {qid}',
                                               'preview_url': urljoin(client.base_url, a['href'])})
    else:
        course_ids = list(courses) if scope != 'all' else [x['id'] for x in client.get_courses()]
        routes = []
        if scope in {'category', 'bank'}:
            routes = [{'cmid': bank} if bank else {'courseid': courses[0]}]
        else:
            for course in course_ids:
                routes.append({'courseid': course})
                for section in client.get_course_sections(CourseId(course)):
                    for module in section['modules']:
                        if module['modname'] in {'quiz', 'qbank'}:
                            routes.append({'cmid': module['cmid']})
        for route in routes:
            params = {**route, 'qperpage': 1000}
            if category:
                params['filter'] = json.dumps({'category': {'name': 'category', 'jointype': 1, 'values': [category],
                                                          'filteroptions': [{'name': 'includesubcategories', 'value': True}]}})
            url = client.base_url + '/question/edit.php?' + urlencode(params)
            questions.update(_listing(client, url))
    counts = Counter(q['id'] for a in attempts for q in a['questions'])
    incorrect = Counter(q['id'] for a in attempts for q in a['questions'] if q['mark'] < q['maxmark'])
    for qid, q in questions.items():
        # Keep an exact-version, credential-free URL for Moodle's own rendering.
        original = urlparse(q['preview_url'])
        context = parse_qs(original.query)
        allowed = {key: context[key][0] for key in ('cmid', 'courseid') if context.get(key)}
        allowed['id'] = qid
        q['moodle_url'] = client.base_url.rstrip('/') + original.path + '?' + urlencode(allowed)
        if view == 'moodle':
            q['html'], q['warnings'] = '', []
        elif 'html' not in q:
            doc = _get(client, q['preview_url'])
            node = doc.select_one('.que')
            if not node:
                raise ReviewError(f'No preview available for question {qid}; export stopped.')
            q['html'], q['warnings'] = _content(node, client)
        q.pop('preview_url', None)
        q['attempt_count'] = counts[qid] if attempts else None
        q['incorrect_count'] = incorrect[qid] if attempts else None
    if not questions:
        raise ReviewError('No questions found. Check the course/bank context and permissions.')
    source = {'base_url': client.base_url.rstrip('/'), 'scope': scope, 'quiz_id': quiz,
              'course_ids': list(courses), 'category_id': category, 'bank_id': bank,
              'attempt_count': len(attempts) if scope in {'quiz', 'attempted'} else None,
              'title': (quiz_title or f'Quiz {quiz}') if quiz else f'{scope.title()} question review'}
    return {'schema_version': 2, 'review_id': str(uuid.uuid4()), 'created_at': datetime.now(timezone.utc).isoformat(),
            'source': {**source, 'view': view}, 'questions': sorted(questions.values(), key=lambda x: (x['name'], x['id']))}


def save_review(review, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if any((directory / name).exists() for name in ('review.json', 'review.html')):
        raise ReviewError('Review files already exist; choose a new output directory.')
    template = Path(__file__).resolve().parents[1] / 'review_assets' / 'reviewer.html'
    encoded = json.dumps(review, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    (directory / 'review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
    (directory / 'review.html').write_text(template.read_text(encoding='utf-8').replace('__REVIEW_DATA__', encoded), encoding='utf-8')
    return directory / 'review.html'


def make_credit_plan(client, quiz, review, selection, *, action=None):
    version = selection.get('schema_version')
    if version not in {1, 2} or selection.get('review_id') != review.get('review_id'):
        raise ReviewError('Selection belongs to a different review.')
    if version == 2 and (selection.get('intent') != 'review' or action != 'full-credit'):
        raise ReviewError('These are review flags, not grading instructions. Choose edit/remove/exclude, or explicitly use --action full-credit for grading.')
    if action not in {None, 'full-credit'}:
        raise ReviewError('This command only previews full-credit grading. Edits/removals are separate actions.')
    base = client.base_url.rstrip('/')
    if review['source']['base_url'] != base or selection.get('base_url') != base:
        raise ReviewError('Review/selection belongs to a different Moodle site.')
    if review['source'].get('quiz_id') and review['source']['quiz_id'] != quiz:
        raise ReviewError('Review belongs to another quiz.')
    if not selection.get('complete'):
        raise ReviewError('Finish reviewing all cards before creating a grade plan.')
    selected = selection.get('selected_question_ids', [])
    available = {q['id'] for q in review['questions']}
    if not selected or any(type(q) is not int or q not in available for q in selected):
        raise ReviewError('Selection is empty or contains IDs absent from this review.')
    decisions = selection.get('decisions', {})
    if not isinstance(decisions, dict) or set(decisions) != {str(q) for q in available} or any(v not in ({'keep', 'flag'} if version == 2 else {'keep', 'full_credit'}) for v in decisions.values()):
        raise ReviewError('Selection does not contain a decision for every review card.')
    if {int(k) for k, value in decisions.items() if value == ('flag' if version == 2 else 'full_credit')} != set(selected):
        raise ReviewError('Selected IDs disagree with the card decisions.')
    attempts = attempt_snapshot(client, quiz)
    for attempt in attempts:
        total = sum(q['maxmark'] for q in attempt['questions'])
        attempt['after'] = sum(max(q['mark'], q['maxmark']) if q['id'] in selected else q['mark'] for q in attempt['questions']) / total * attempt['max_grade']
    return {'schema_version': 1, 'plan_id': str(uuid.uuid4()), 'base_url': base, 'quiz_id': quiz,
            'review_id': review['review_id'], 'selected_question_ids': sorted(set(selected)),
            'created_at': datetime.now(timezone.utc).isoformat(), 'policy': 'full_credit',
            'retire_questions': False, 'attempts': attempts,
            'not_attempted_ids': sorted(set(selected) - {q['id'] for a in attempts for q in a['questions']})}


def _same_attempts(expected, actual, credited=()):
    if {a['id'] for a in expected} != {a['id'] for a in actual}:
        raise ReviewError('Attempt set changed since preview. Create a new plan.')
    for old in expected:
        new = next(a for a in actual if a['id'] == old['id'])
        if new['max_grade'] != old['max_grade'] or len(new['questions']) != len(old['questions']):
            raise ReviewError('Quiz grading configuration changed since preview.')
        for q, live in zip(old['questions'], new['questions']):
            target = q['maxmark'] if (old['id'], q['slot']) in credited else q['mark']
            if any(q[k] != live[k] for k in ('id', 'slot', 'maxmark', 'text_hash', 'response_hash')) or live['mark'] != target:
                raise ReviewError('Question, response, or grade changed since preview. Create a new plan.')


def apply_credit_plan(client, plan, journal_path):
    if plan.get('schema_version') != 1 or plan.get('policy') != 'full_credit' or plan.get('retire_questions') is not False:
        raise ReviewError('Unsupported plan; only full-credit mark corrections are supported.')
    if plan.get('base_url') != client.base_url.rstrip('/'):
        raise ReviewError('Plan belongs to another Moodle site.')
    journal = Path(journal_path)
    if journal.exists():
        raise ReviewError('Journal exists. Inspect partial results and create a fresh plan; do not replay blindly.')
    selected = set(plan['selected_question_ids'])
    if not selected:
        raise ReviewError('No questions selected.')
    before = attempt_snapshot(client, plan['quiz_id'])
    _same_attempts(plan['attempts'], before)
    changes = [(a, q) for a in before for q in a['questions'] if q['id'] in selected and q['mark'] < q['maxmark']]
    credited = set()
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open('x', encoding='utf-8') as log:
        for attempt, question in changes:
            aid, slot = attempt['id'], question['slot']
            page = _get(client, '/mod/quiz/comment.php', attempt=aid, slot=slot)
            form = page.select_one('form[action*="comment.php"]')
            if not form or not form.select_one('.qtext'):
                raise ReviewError('Manual grading form unavailable. Inspect the journal before retrying.')
            if _hash(form.select_one('.qtext')) != question['text_hash']:
                raise ReviewError('The grading form shows different question content.')
            data = {}
            for field in form.select('input[name], textarea[name]'):
                kind = field.get('type', '')
                name = field['name']
                grading = name.endswith(('_-mark', '_-maxmark', '_-comment', '_-comment:itemid', '_-commentformat', '_:sequencecheck', '_:minfraction', '_:maxfraction'))
                routing = name in {'attempt', 'slot', 'slots', 'sesskey'} and kind == 'hidden'
                save = name in {'submit', 'submitbutton'} and kind == 'submit'
                if field.has_attr('disabled') or not (grading or routing or save):
                    continue
                data[name] = field.get_text() if field.name == 'textarea' else field.get('value', '')
            marks, comments = ([k for k in data if k.endswith(ending)] for ending in ('_-mark', '_-comment'))
            if len(marks) != 1 or len(comments) != 1 or _number(data[marks[0]]) != question['mark']:
                raise ReviewError('Grade changed or the grading form is unsupported.')
            data[marks[0]] = str(question['maxmark'])
            data[comments[0]] += f'\n<p>Full credit awarded following instructor review. Question version {question["id"]}. Original response retained.</p>'
            action = urljoin(client.base_url, form['action'])
            if _origin(action) != _origin(client.base_url):
                raise ReviewError('Unexpected grading form destination.')
            record = {'plan_id': plan['plan_id'], 'attempt': aid, 'slot': slot, 'question_id': question['id'],
                      'before': question['mark'], 'after': question['maxmark']}
            log.write(json.dumps({**record, 'state': 'pending'}) + '\n')
            log.flush()
            response = client._session.post(action, data=data, headers={'Content-Type': 'application/x-www-form-urlencoded', 'Referer': client.base_url + '/mod/quiz/comment.php'}, timeout=30)
            response.raise_for_status()
            live = _get(client, '/mod/quiz/reviewquestion.php', attempt=aid, slot=slot)
            grade = live.select_one('.que .grade')
            values = re.findall(r'-?\d+(?:\.\d+)?', grade.get_text() if grade else '')
            if len(values) != 2 or _number(values[0]) != question['maxmark']:
                raise ReviewError('Save unverified. Inspect the journal before retrying.')
            credited.add((aid, slot))
            log.write(json.dumps({**record, 'state': 'verified'}) + '\n')
            log.flush()
        after = attempt_snapshot(client, plan['quiz_id'])
        _same_attempts(before, after, credited)
        for attempt in after:
            old = next(a for a in before if a['id'] == attempt['id'])
            expected = sum(max(q['mark'], q['maxmark']) if q['id'] in selected else q['mark'] for q in old['questions']) / sum(q['maxmark'] for q in old['questions']) * old['max_grade']
            if abs(attempt['before'] - expected) > .011:
                raise ReviewError('Final report grade differs from the expected full-credit total.')
        log.write(json.dumps({'plan_id': plan['plan_id'], 'state': 'complete', 'changes': len(changes)}) + '\n')
    return len(changes)

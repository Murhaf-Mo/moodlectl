"""Create offline swipe reviews, preview grading changes, then apply approved plans."""
from __future__ import annotations

import json
import webbrowser
from pathlib import Path

import requests
import typer

from moodlectl.client import MoodleClient
from moodlectl.config import Config
from moodlectl.features import question_review as feature
from moodlectl.output.formatters import print_table

app = typer.Typer(help='Review question cards and preview/apply full credit after submissions.')


def _client():
    return MoodleClient.from_config(Config.load())


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _error(exc):
    typer.echo(f'Error: {exc}', err=True)
    raise typer.Exit(1) from exc


@app.command('create')
def create_review(
    scope: str = typer.Option('quiz', help='quiz, attempted, bank, category, course, or all accessible courses.'),
    quiz: int | None = typer.Option(None, '--quiz', '-q', help='Quiz activity cmid.'),
    course: list[int] | None = typer.Option(None, '--course', '-c', help='Course ID; repeat for multiple courses.'),
    category: int | None = typer.Option(None, help='Category ID; category scope includes its subcategories.'),
    bank: int | None = typer.Option(None, help='Question-bank/quiz cmid for bank scope or category scope on Moodle 5.'),
    output: Path = typer.Option(..., '--output', '-o', help='New output directory for review.html and review.json.'),
    open_browser: bool = typer.Option(False, '--open', help='Open the generated local HTML reviewer.'),
):
    """Export question cards. Does not change student marks or question status.

    Review all cards, then export your selection JSON from the final screen.
    Scope quiz includes pool questions and versions used in existing attempts;
    attempted includes only versions actually given to students.
    """
    try:
        review = feature.collect_review(_client(), scope, quiz=quiz, courses=course or [], category=category, bank=bank)
        path = feature.save_review(review, output).resolve()
    except (RuntimeError, ValueError, OSError, requests.RequestException) as exc:
        _error(exc)
    typer.echo(f'{len(review["questions"])} question cards saved: {path}')
    typer.echo('Review the cards and export your selection. Then run moodlectl review preview.')
    if open_browser:
        webbrowser.open(path.as_uri())


@app.command('preview')
def preview_credit(
    quiz: int = typer.Option(..., '--quiz', '-q', help='The quiz to correct; never inferred from a course-wide review.'),
    review: Path = typer.Option(..., exists=True, dir_okay=False, help='review.json from review create.'),
    selection: Path = typer.Option(..., exists=True, dir_okay=False, help='Selection JSON downloaded from the reviewer.'),
    output: Path = typer.Option(..., '--output', '-o', help='New JSON plan file, including the before snapshot.'),
):
    """Calculate before/after attempt grades. Does not write marks to Moodle."""
    try:
        if output.exists():
            raise feature.ReviewError('Plan already exists; choose a new output filename.')
        plan = feature.make_credit_plan(_client(), quiz, _read(review), _read(selection))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    except (RuntimeError, ValueError, OSError, requests.RequestException) as exc:
        _error(exc)
    rows = [{'student': a['student'], 'attempt': a['id'], 'before': f'{a["before"]:.2f}',
             'after': f'{a["after"]:.2f}', 'out_of': a['max_grade']} for a in plan['attempts']]
    print_table(rows, ['student', 'attempt', 'before', 'after', 'out_of'], fmt='table')
    if plan['not_attempted_ids']:
        typer.echo(f'Not used in submitted attempts (no changes): {plan["not_attempted_ids"]}')
    typer.echo(f'Preview saved: {output.resolve()}')
    typer.echo('These are attempt grades; the quiz grading method determines the final student grade when multiple attempts exist.')
    typer.echo('Question retirement is not included. Ask separately whether to exclude questions from future draws.')


@app.command('apply')
def apply_credit(
    plan: Path = typer.Option(..., exists=True, dir_okay=False, help='Approved plan JSON from review preview.'),
    journal: Path = typer.Option(..., help='New journal path; records pending and verified mark changes.'),
    yes: bool = typer.Option(False, '--yes', '-y', help='Apply an already approved plan without a terminal prompt.'),
):
    """Apply full credit and verify unchanged responses and unaffected marks.

    Never deletes attempts or changes answer keys/status. For a failed/partial
    application, inspect the journal and create a fresh preview before retrying.
    """
    try:
        data = _read(plan)
        count = sum(q['id'] in data['selected_question_ids'] and q['mark'] < q['maxmark']
                    for a in data['attempts'] for q in a['questions'])
        typer.echo(f'Quiz {data["quiz_id"]}: award full credit for {count} question responses. No question retirement.')
        if not yes:
            typer.confirm('Apply this grading plan?', abort=True)
        changed = feature.apply_credit_plan(_client(), data, journal)
    except (RuntimeError, ValueError, OSError, requests.RequestException) as exc:
        _error(exc)
    typer.echo(f'Verified {changed} mark changes. Submissions and other marks preserved. Journal: {journal.resolve()}')

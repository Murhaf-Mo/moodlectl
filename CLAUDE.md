# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`moodlectl` — a CLI tool for automating Moodle LMS tasks at CCK University (Kuwait). It connects via browser session cookies (Microsoft SSO; no programmatic login possible).

## Setup & Commands

```bash
pip install -e ".[dev]"          # install with dev deps
pip install -e ".[dev,export]"   # also enable Excel export

moodlectl --help                 # all commands
pytest                           # run all tests
pytest tests/test_courses.py     # single test file
```

## Credentials

All auth lives in `.env` (never committed). Values expire when the browser session ends — re-login and paste fresh values from:
- `MOODLE_SESSION` → F12 → Application → Cookies → `MoodleSession`
- `MOODLE_SESSKEY` → F12 → Network → any `service.php` request body

`config.py` loads `.env` at import time and exits with instructions if values are missing.

## Architecture

### Request flow
```
CLI command → features/ function → MoodleClient method → HTTP
```

**`client/base.py` (`MoodleClientBase`)** — transport only. Owns the `requests.Session`, browser headers, and two methods: `ajax()` for Moodle's internal AJAX API (`/lib/ajax/service.php`) and `refresh_sesskey()`.

**`client/api.py` (`MoodleAPI`)** — inherits base, one method per data source:
- `get_courses()` — AJAX (`core_course_get_enrolled_courses_by_timeline_classification`)
- `get_course_participants(course_id)` — scrapes `/user/index.php` (AJAX function not registered)
- `get_grade_report(course_id)` — scrapes `/grade/report/grader/index.php`; detects login redirect and raises a clear session-expired error
- `get_assignment_internal_id(cmid)` → `(assignment_id, context_id)` — scrapes grader page for `data-assignmentid` and `data-contextid`; these differ from the cmid and are required for grade submission
- `get_grade_form_fragment(context_id, user_id)` — calls `core_get_fragment` with `mod_assign/gradingpanel` to get a fresh form field dict including a one-time `itemid`; also parses `grade_max` from label "Grade out of X"
- `submit_grade_for_user(cmid, user_id, grade, feedback, notify_student)` — orchestrates the full grade submission: resolves IDs → loads fresh fragment → serializes form → calls `mod_assign_submit_grading_form`; returns `grade_max`
- `get_course_assignments(course_id)` — scrapes `/mod/assign/index.php?id={course_id}`; returns `{cmid, name, due_text, submitted_count}` per assignment
- `get_assignment_submissions(cmid)` — scrapes `/mod/assign/view.php?id={cmid}&action=grading&perpage=1000`; returns `{user_id, fullname, email, status, files:[{filename,url}]}` for submitted entries only (col 8 = file links)
- `download_file(url, dest_path)` — authenticated file download via session; rewrites `webservice/pluginfile.php` → `pluginfile.php` for session-cookie auth
- `send_message()` — AJAX

**`client/__init__.py`** re-exports `MoodleAPI as MoodleClient` — always import from here.

**`features/`** — business logic between client and CLI. Filtering (by `role`, `name`) lives here, not in the client or CLI. `courses._normalise()` handles both API format (roles as list of dicts) and scrape format (roles as plain string).

**`cli/`** — Typer sub-apps, one file per command group, registered in `cli/main.py`. Each command calls `MoodleClient.from_config(Config.load())`. All commands support `--output table|json|csv` passed to `output/formatters.print_table()`. Filtering flags (`--role`, `--name`) are forwarded to `features/`.

`grades show` has four display modes controlled by flags:
- default: summary table — name + course total only; `--course` is optional (omit for all courses)
- `--full`: wide table with every grade item as a column (uses `shorten_columns(max_len=50)`)
- `--cards`: one Rich Panel per student listing every grade item vertically
- `--output csv/json`: full column names including Arabic, UTF-8-SIG encoded for Excel

**`ai/`** — stubs for Claude API integration. `ai/client.py` (`AIClient`) wraps `anthropic.Anthropic`; `ai/grader.py` and `ai/responder.py` are `NotImplementedError` placeholders. Wire them at the CLI layer — features stay AI-free.

### Adding a new feature
1. Add a method to `client/api.py` — if the Moodle AJAX function isn't registered, scrape the page instead
2. Add business logic to `features/<area>.py`
3. Add a CLI command to `cli/<area>.py` and register it in `cli/main.py` if it's a new group
4. Use `output/formatters.print_table(data, columns, fmt)` for output

### Filtering pattern
Filtering is always done in `features/` after fetching — never in the client. CLI flags like `--role student` and `--name "Ali"` are passed as kwargs to the feature function, which does a case-insensitive `in` check on the relevant field.

### Grade report pagination
`get_grade_report()` fetches pages (`?page=0`, `?page=1`, …) until a page returns fewer than 20 rows. Column headers are parsed only from page 0. `shorten_columns()` in `features/grades.py` strips Arabic parenthesised suffixes and truncates — pass `max_len=50` for the `--full` view.

### Grade submission and inspection
`moodlectl grading show-grade` reads the current grade and feedback for a student without writing anything: calls `get_assignment_internal_id(cmid)` then `get_grade_form_fragment(context_id, user_id)` and prints the `grade` and `assignfeedbackcomments_editor[text]` fields.

`moodlectl grading submit` calls `client.submit_grade_for_user(cmid, user_id, grade)` which does three steps:
1. Scrape grader page to get `(assignment_id, context_id)` — these are different from the cmid
2. Call `core_get_fragment` (`mod_assign/gradingpanel`) to get a fresh form with a one-time `itemid` for the feedback editor — **must be fetched immediately before submission**, not cached
3. Call `mod_assign_submit_grading_form(assignmentid, userid, jsonformdata)` with the URL-encoded form; empty list response = success, non-empty = validation error

The grade scale ("out of X") is parsed from the label "Grade out of X" in the fragment HTML. The cmid shown in `assignments list` is the course-module ID; the internal `assignmentid` is different and resolved at submission time.

### Assignment downloads and visibility
`features/assignments.py` public functions:
- `list_assignments(client, course_ids, status)` — `status` is `active` (future due date or none), `past`, or `all`. Due dates are parsed from Moodle text format `"%A, %d %B %Y, %I:%M %p"`.
- `download_submissions(client, course_ids, course_map, status, out_dir)` — downloads to `{out_dir}/{course_short}/{active|past}/{assignment}/{student_name_id}/file`. `course_map` is `{course_id: course_dict}` from `get_courses()`.
- `get_missing_submissions(client, cmid, course_id)` — returns students enrolled as `student` role who have no entry in `get_assignment_submissions(cmid)`; used by `assignments missing`.

CLI commands `assignments submissions` and `assignments missing` call the client/features directly without downloading any files.

`_safe_name()` strips filesystem-illegal characters and limits to 80 chars. The CLI resolves course IDs from `get_courses()` when `--course` is omitted. Assignments with `submitted_count == 0` are skipped without scraping the grading page.

### Windows Unicode (cp1252)
`cli/main.py` calls `sys.stdout.reconfigure(encoding="utf-8")` at startup — this fixes UnicodeEncodeError for Arabic in assignment names and course names when printing Rich tables. `output/formatters.py` uses `Console(legacy_windows=False)` to use ANSI instead of the Win32 console API. CSV output uses `utf-8-sig` (BOM) for Excel compatibility.

### AJAX vs scraping
Not all Moodle functions are exposed via `/lib/ajax/service.php`. Test with a raw `ajax()` call first; if it returns `"Can't find data record in database table external_functions"`, scrape the page instead. Grade pages redirect to `/login/index.php` when the session is expired — check `resp.url` after following redirects.

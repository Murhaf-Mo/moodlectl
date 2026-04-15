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
- `get_assignment_submissions(cmid)` — scrapes `/mod/assign/view.php?id={cmid}&action=grading&perpage=1000`; returns `{user_id, fullname, email, status, grading_status, files:[{filename,url}]}` for submitted entries only. `grading_status` contains the grade value (e.g. `"Grade10.00 / 10.00"`) when graded, or `"-"` / empty when not yet graded.
- `get_assignment_brief_files(cmid)` — scrapes the assignment view page for instructor-attached files (`mod_assign/introattachment`)
- `download_file(url, dest_path)` — authenticated file download via session; rewrites `webservice/pluginfile.php` → `pluginfile.php` for session-cookie auth
- `send_message(user_id, message)` / `delete_message(message_id)` — AJAX

**`client/__init__.py`** re-exports `MoodleAPI as MoodleClient` — always import from here.

**`features/`** — business logic between client and CLI. Filtering (by `role`, `name`) lives here, not in the client or CLI.

**`cli/`** — Typer sub-apps, one file per command group, registered in `cli/main.py`. Each command calls `MoodleClient.from_config(Config.load())`. All commands support `--output table|json|csv` passed to `output/formatters.print_table()`.

### Command groups

| Group | Commands | Purpose |
|---|---|---|
| `auth` | `check` | Verify session validity before long operations |
| `courses` | `list`, `participants`, `inactive` | Enrolled courses and participants |
| `grades` | `show`, `stats` | Grade reports and statistics |
| `assignments` | `list`, `info`, `submissions`, `missing`, `ungraded`, `remind`, `remind-all`, `due-soon`, `download` | Assignment management |
| `grading` | `show`, `submit`, `batch`, `next` | Grade submission |
| `messages` | `send`, `delete` | Direct messaging |
| `summary` | (top-level) | Quick overview of upcoming deadlines |

### Key design decisions

**`assignments missing`** handles both single-assignment and bulk modes:
- With `--assignment` + `--course` → single assignment view (calls `get_missing_submissions`)
- Without `--assignment` → bulk scan across all courses (calls `get_all_missing_submissions`)

**`grading show`** was previously `grading show-grade` — renamed for consistency with other `show` commands.

**`grading batch`** reads a CSV with columns `user_id, grade, feedback` (feedback optional). Always use `--dry-run` first. Notifications are suppressed during batch grading.

**`grading next`** is an interactive loop: fetches all ungraded submissions, shows each student's details, prompts for grade and optional feedback, submits immediately, and continues to the next. Ctrl+C stops cleanly.

**`courses inactive`** works with or without `--course`. Without it, `get_all_inactive_students()` iterates all enrolled courses and adds a `course` column to the results. With `--course`, calls `get_inactive_students()` for a single course (no course column). Both parse Moodle lastaccess text ("3 days 14 hours", "Never", etc.) via `_parse_lastaccess_days()`. Unparseable entries are included with `inactive_days="?"` to avoid silent omissions.

**`grades stats`** computes mean, median, std_dev, min, max from the Course Total column using Python's `statistics` module.

**`assignments due-soon`** reads `due_dt` from `list_assignments()` results and filters to `now < due_dt < now + timedelta(days=N)`.

**`assignments remind` / `remind-all`** chain `get_missing_submissions` → `client.send_message()`. Always offer `--dry-run`.

### `features/` public API

**`features/assignments.py`:**
- `list_assignments(client, course_ids, status)` — status: `active`, `past`, `all`; returns dicts with `due_dt` (parsed datetime or None)
- `get_missing_submissions(client, cmid, course_id)` → `[{user_id, fullname, email, lastaccess}]`
- `get_all_missing_submissions(client, course_ids, course_map, status)` → flat list with course/assignment context
- `get_all_ungraded_submissions(client, course_ids, course_map, status)` → submitted entries with no grade
- `is_ungraded(submission)` → True if `grading_status` contains no digits
- `remind_missing_students(client, cmid, course_id, message_text)` → sends message to each missing student
- `remind_all_missing_students(client, course_ids, course_map, message_text, status)` → bulk version
- `get_due_soon(client, course_ids, course_map, days)` → assignments due within N days, sorted by urgency
- `download_submissions(client, course_ids, course_map, status, out_dir, ungraded_only)` → downloads files

**`features/grades.py`:**
- `get_grade_report(client, course_id, name)` → `{columns, rows}`
- `shorten_columns(columns, max_len)` → `{original: short}` mapping for display
- `compute_stats(report)` → `{column, count, mean, median, std_dev, min, max}`

**`features/grading.py`:**
- `submit_grade(client, cmid, user_id, grade, feedback, notify_student)` → `{user_id, grade, grade_max, grade_pct, feedback}`
- `batch_grade(client, cmid, rows, dry_run)` → list of result dicts with `ok` and `error` fields

**`features/courses.py`:**
- `list_courses(client)`, `get_participants(client, course_id, role, name)`, `get_all_participants`
- `get_inactive_students(client, course_id, days)` → students inactive for ≥ days
- `_parse_lastaccess_days(text)` → int or None (internal helper)
- `_normalise(user)` → handles both API format (roles as list of dicts) and scrape format (roles as string)

### Grade submission internals
`grading submit` / `grading batch` / `grading next` all call `client.submit_grade_for_user()` which does:
1. Scrape grader page → `(assignment_id, context_id)` — different from cmid
2. Call `core_get_fragment` (`mod_assign/gradingpanel`) → fresh form with one-time `itemid` — **must be fetched immediately before submission**, not cached
3. Call `mod_assign_submit_grading_form` — empty list response = success; non-empty = validation error

The grade scale ("out of X") is parsed from the label "Grade out of X" in the fragment HTML.

### Grade report pagination
`get_grade_report()` fetches pages (`?page=0`, `?page=1`, …) until fewer than 20 rows are returned. Column headers are parsed only from page 0. `shorten_columns()` strips Arabic parenthesised suffixes and truncates — pass `max_len=50` for `--full` view.

### Adding a new feature
1. Add a method to `client/api.py` — if the AJAX function isn't registered, scrape the page instead
2. Add business logic to `features/<area>.py`
3. Add a CLI command to `cli/<area>.py` and register it in `cli/main.py` if it's a new group
4. Use `output/formatters.print_table(data, columns, fmt)` for output

### Filtering pattern
Filtering is always done in `features/` after fetching — never in the client. CLI flags like `--role student` and `--name "Ali"` are passed as kwargs to the feature function, which does a case-insensitive `in` check.

### Windows Unicode (cp1252)
`cli/main.py` calls `sys.stdout.reconfigure(encoding="utf-8")` at startup — this fixes UnicodeEncodeError for Arabic names. `output/formatters.py` uses `Console(legacy_windows=False)` to use ANSI instead of the Win32 console API. CSV output uses `utf-8-sig` (BOM) for Excel compatibility.

### AJAX vs scraping
Test with a raw `ajax()` call first; if it returns `"Can't find data record in database table external_functions"`, scrape the page instead. Grade pages redirect to `/login/index.php` when the session is expired — check `resp.url` after following redirects.

**`ai/`** — stubs for Claude API integration. `ai/client.py` (`AIClient`) wraps `anthropic.Anthropic`; `ai/grader.py` and `ai/responder.py` are `NotImplementedError` placeholders. Wire them at the CLI layer — features stay AI-free.

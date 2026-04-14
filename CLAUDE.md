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
- `get_assignments()`, `send_message()` — AJAX

**`client/__init__.py`** re-exports `MoodleAPI as MoodleClient` — always import from here.

**`features/`** — business logic between client and CLI. Filtering (by `role`, `name`) lives here, not in the client or CLI. `courses._normalise()` handles both API format (roles as list of dicts) and scrape format (roles as plain string).

**`cli/`** — Typer sub-apps, one file per command group, registered in `cli/main.py`. Each command calls `MoodleClient.from_config(Config.load())`. All commands support `--output table|json|csv` passed to `output/formatters.print_table()`. Filtering flags (`--role`, `--name`) are forwarded to `features/`.

`grades show` has three display modes controlled by flags:
- default (`table`): summary — name + course total only
- `--full`: vertical panel per student showing every grade item (uses `shorten_columns(max_len=50)`)
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

### AJAX vs scraping
Not all Moodle functions are exposed via `/lib/ajax/service.php`. Test with a raw `ajax()` call first; if it returns `"Can't find data record in database table external_functions"`, scrape the page instead. Grade pages redirect to `/login/index.php` when the session is expired — check `resp.url` after following redirects.

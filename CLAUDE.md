# CLAUDE.md

Guidance for Claude Code when working in this repository. See `README.md` for installation, commands, and usage.

## Dev commands

```bash
pip install -e ".[dev,export,analytics]"   # full install
pytest                                      # run all tests
pytest tests/test_courses.py               # single file
ruff check .                               # lint
```

## Architecture

```
CLI command → features/ function → MoodleClient method → HTTP
```

- **`client/base.py` (`MoodleClientBase`)** — transport only: `requests.Session`, `ajax()`, `refresh_sesskey()`
- **`client/api.py` (`MoodleAPI`)** — one method per data source; inherits base
- **`client/__init__.py`** — re-exports `MoodleAPI as MoodleClient`; always import from here
- **`features/`** — business logic; filtering lives here, never in client or CLI
- **`cli/`** — Typer sub-apps, one per command group, registered in `cli/main.py`
- **`moodlectl/types.py`** — all public TypedDicts and NewTypes; every layer imports from here

## Non-obvious constraints

### AJAX vs scraping

Try `ajax()` first. If it returns `"Can't find data record in database table external_functions"`, scrape the page
instead. Grade pages redirect to `/login/index.php` on expired sessions — check `resp.url` after following redirects.

### Grade submission is a 3-step process

`client.submit_grade_for_user()` must:

1. Scrape the grader page → `(assignment_id, context_id)` — these differ from `cmid`
2. Call `core_get_fragment` (`mod_assign/gradingpanel`) → fresh form with a one-time `itemid` — **fetch immediately
   before submit, never cache**
3. Call `mod_assign_submit_grading_form` — empty list = success; non-empty = validation error

Grade scale ("out of X") is parsed from the label `"Grade out of X"` in the fragment HTML.

### Grade report pagination

`get_grade_report()` fetches `?page=0`, `?page=1`, … until a page returns fewer than 20 rows. Column headers are parsed
only from page 0.

### ID types

`Cmid`, `UserId`, `CourseId` are semantic `NewType`s — never mix them. Cast plain ints at the CLI boundary only:

```python
CourseId(course_id), Cmid(cmid)
```

### Filtering pattern

All filtering (by `role`, `name`, etc.) happens in `features/` after fetching — case-insensitive `in` check. Never
filter in the client or CLI layer.

### Windows Unicode

`cli/main.py` calls `sys.stdout.reconfigure(encoding="utf-8")` at startup to handle Arabic names on cp1252 terminals.
`output/formatters.py` uses `Console(legacy_windows=False)` for ANSI. CSV uses `utf-8-sig` (BOM) for Excel.

### `is_ungraded(submission)`

Returns `True` if `grading_status` contains no digits. The field looks like `"Grade10.00 / 10.00"` when graded.

### `_normalise(user)` in `features/courses.py`

Handles two shapes: API format (roles as list of dicts) and scrape format (roles as string). Don't add a third path
without updating both call sites.

## Adding a new feature

1. Add a method to `client/api.py` (scrape if AJAX function isn't registered)
2. Add TypedDicts to `moodlectl/types.py`; add to `MoodleClientProtocol` if it's a client method
3. Add business logic to `features/<area>.py`
4. Add CLI command to `cli/<area>.py`; register in `cli/main.py` for new groups
5. Use `output/formatters.print_table(data, columns, fmt)` for table output
6. For charts use `output/charts.py` — gate behind `[analytics]` if adding a new dependency

## `ai/` stubs

`ai/client.py` (`AIClient`) wraps `anthropic.Anthropic`. `ai/grader.py` and `ai/responder.py` are `NotImplementedError`
placeholders. Wire at the CLI layer — features must stay AI-free.
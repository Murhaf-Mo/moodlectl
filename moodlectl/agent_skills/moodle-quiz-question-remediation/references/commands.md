# CLI workflow

Use `moodlectl review --help` for the installed version's commands. The default
reviewer displays the original Moodle question in a reusable browser window.
The local page records **Keep / Needs changes** decisions; actions are chosen later.

## Discover and authenticate

```bash
moodlectl auth check
moodlectl auth login
moodlectl courses list
moodlectl quizzes list --course COURSE_ID
moodlectl quizzes info --quiz QUIZ_CMID
moodlectl questions list-categories --course COURSE_ID
```

Run from the directory with the correct `.env`. On Moodle 5, a category can require
the bank or quiz activity cmid (`--bank`). The CLI session does not sign the user's
normal browser into Moodle: the preview window may require browser sign-in.

## Choose a review scope

Each command writes `review.html` and `review.json` into a new directory. `--open`
opens the local reviewer. Click **Open Moodle preview** once to enable synchronized
question navigation. Browser popup blockers may require that user click. Question
links contain only the exact question-version ID and course/module context, never
session credentials. Keep the original-preview window open while reviewing.

```bash
moodlectl review create --view moodle --scope quiz --quiz QUIZ_CMID --output ./quiz-review --open
moodlectl review create --view moodle --scope attempted --quiz QUIZ_CMID --output ./attempted-review
moodlectl review create --view moodle --scope bank --bank BANK_CMID --output ./bank-review
moodlectl review create --view moodle --scope category --course COURSE_ID --category CATEGORY_ID --bank BANK_CMID --output ./category-review
moodlectl review create --view moodle --scope course --course COURSE_ID --output ./course-review
moodlectl review create --view moodle --scope course --course COURSE_A --course COURSE_B --output ./courses-review
moodlectl review create --view moodle --scope all --output ./all-banks-review
```

Scope `quiz` includes current fixed/pool questions and versions students received.
Scope `attempted` includes only versions actually given to students. Different
versions are not silently merged. Scope is chosen at export time; change it by
creating another export. The current quiz/attempted collector requires finished,
numerically graded attempts if attempts exist; unattempted quizzes work too.

For a self-contained offline view, request `--view offline`. It embeds passive
question content and same-site raster images; check its media warnings and Moodle
for unsupported displays. Treat all review artifacts as private exam information.

## Flags and the next action

After reviewing every card, export decisions. Schema 2 uses `intent: "review"`,
`decisions` with `keep|flag`, and `selected_question_ids`; it does not select a Moodle
mutation. Older saved `full_credit` decisions are migrated to neutral flags in the
updated UI so the instructor can reconsider the action.

With no attempts, discuss editing/replacing/removing the flagged questions or
excluding them from pools. Do not run a grade correction just because flags exist.
The CLI currently has no automated edit/remove command; use the verified Moodle
UI/API after the instructor chooses a concrete action. Deleting questions from the
bank is distinct from removing them from a quiz and must not be inferred.

## Preview full credit when chosen

```bash
moodlectl review preview --action full-credit --quiz QUIZ_CMID --review ./quiz-review/review.json --selection ./selection.json --output ./credit-plan.json
```

Generic schema-2 flags require the explicit `--action full-credit`; otherwise the
command stops. Legacy schema-1 full-credit exports remain readable. This command
reads all report pages, clears grading/regrade filters, and creates a private
snapshot of IDs, per-attempt slots/marks, and response/content fingerprints.
It prints attempt grades, not an assertion about the final gradebook result when
several attempts exist. It reports selected questions not used in submissions.

After the instructor approves that exact plan:

```bash
moodlectl review apply --plan ./credit-plan.json --journal ./credit-journal.jsonl
# For a plan already approved in this session:
moodlectl review apply --plan ./credit-plan.json --journal ./credit-journal.jsonl --yes
```

It refuses stale snapshots, uses fresh per-response grading forms, preserves existing
comments and student answers, and verifies the save and final report. An existing
journal blocks replay; inspect partial results and create a new preview after a
failure. Question retirement is never bundled into this grading command.

UI equivalents: Quiz → Results → Grades → Review attempt → Make comment or override
mark → full mark → Save. For separately approved future exclusion: Question bank →
Status → Draft, after checking all versions and pool capacity.

## Agent discovery

```bash
moodlectl skills list
moodlectl skills show moodle-quiz-question-remediation
moodlectl skills path moodle-quiz-question-remediation
```

The skill ships with the package; `AGENTS.md` points repository agents to it.
Copy its folder into the agent's skills directory for automatic discovery (Codex:
`~/.codex/skills/`, then start a new session). Discovery commands do not authenticate
or mutate Moodle, even with `MOODLE_AUTO_LOGIN=true`.

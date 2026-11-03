# CLI workflow

Run `moodlectl review --help` and each subcommand's `--help` if the installed version
differs. The commands below are built into moodlectl; no browser automation or
web-hosting service is needed for the reviewer.

## Discover the destination

```bash
moodlectl courses list
moodlectl quizzes list --course COURSE_ID
moodlectl questions list-categories --course COURSE_ID
```

On Moodle 5, category operations may need the question-bank or quiz activity cmid;
pass `--bank BANK_CMID` to `review create --scope category`.

## Choose a scope

Each command writes `review.html` and `review.json` into a **new** directory.
`--open` opens the HTML in the default browser; otherwise use the agent environment's
supported local preview mechanism. Scope is chosen before export; changing scope
requires a new export, because the offline page cannot query Moodle.

```bash
moodlectl review create --scope quiz --quiz QUIZ_CMID --output ./quiz-review --open
moodlectl review create --scope attempted --quiz QUIZ_CMID --output ./attempted-review --open
moodlectl review create --scope bank --bank BANK_CMID --output ./bank-review
moodlectl review create --scope category --course COURSE_ID --category CATEGORY_ID --bank BANK_CMID --output ./category-review
moodlectl review create --scope course --course COURSE_ID --output ./course-review
moodlectl review create --scope course --course COURSE_A --course COURSE_B --output ./courses-review
moodlectl review create --scope all --output ./all-banks-review
```

The HTML shows passive question content and embedded same-site raster images. It
uses no session cookies or credentials. Unsupported embedded media is flagged;
check such questions in Moodle. Treat both the HTML and JSON as private exam content.
Question IDs identify exact versions; the quiz scope includes earlier versions used
in attempts alongside currently available pool questions. Attempted scope currently
requires finished, numerically graded attempts, as do correction plans. Unsupported
report layouts or grading totals stop the export/plan rather than guess.

## Preview the selected quiz

After the instructor reviews all cards and exports decisions:

```bash
moodlectl review preview --quiz QUIZ_CMID --review ./quiz-review/review.json --selection ./selection.json --output ./credit-plan.json
```

This reads all attempt-report pages and creates a private before snapshot with
question IDs, per-attempt slots, marks, maximum marks, and response/text fingerprints.
It prints before/after **attempt** grades. It does not change Moodle grades.
Selection files are bound to a review ID and Moodle site, and quiz-scoped exports
are bound to that quiz. Course/bank exports require the quiz to be supplied explicitly.
Questions not given in submitted attempts are reported separately.

## Apply an approved plan

```bash
moodlectl review apply --plan ./credit-plan.json --journal ./credit-journal.jsonl
# Only when the exact plan has already been approved:
moodlectl review apply --plan ./credit-plan.json --journal ./credit-journal.jsonl --yes
```

The command re-reads attempts before writing, refuses stale snapshots, fetches each
fresh manual-grading form, preserves existing comments, and does not post student
answer controls. It records pending writes before submission and verifies each mark
and the final report. An existing journal blocks replay. If interrupted, inspect
both the journal and Moodle, then create a fresh preview against the current state.
No retirement is bundled into this command.

UI equivalents: Quiz → Results → Grades → Review attempt → Make comment or override
mark → enter the full question mark → Save. Future exclusion, when separately
requested: Question bank → Questions → Status → Draft, after checking pool capacity
and version eligibility.

## Agent discovery

```bash
moodlectl skills list
moodlectl skills show moodle-quiz-question-remediation
moodlectl skills path moodle-quiz-question-remediation
```

The skill and references ship with the package. Copy the directory printed by
`skills path` to the agent's skill directory if automatic discovery is needed.
For Codex, use `~/.codex/skills/` and start a new session. Repository agents find
this skill through `AGENTS.md`. The discovery commands do not authenticate or mutate
Moodle even when `MOODLE_AUTO_LOGIN=true`.

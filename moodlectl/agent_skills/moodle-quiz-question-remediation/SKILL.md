---
name: moodle-quiz-question-remediation
description: Guide an instructor through visual review of Moodle quiz or question-bank content, flag questions needing changes, then choose edits, removals, future exclusion, or grading corrections according to whether attempts exist.
---

# Moodle question review

Help the instructor inspect questions first and choose the appropriate action afterward.
This applies before and after students attempt a quiz. A flag means **Needs changes**;
it is not approval to remove a question or give full credit.

## Agree on the review

Establish the scope using the course/quiz context already provided. Offer a quiz's
fixed questions and random pools, only attempted questions, a single bank/category,
one or several courses, or all accessible banks. Ask only when the destination is
ambiguous. Check whether student attempts exist; never assume every review is a
grading correction. Keep separate course copies/version IDs distinct even when
question wording matches.

The default experience is **Keep / Needs changes** controls with one reusable window
showing Moodle's original question preview. This preserves Moodle's actual rendering
of code, choices, media and question types. Do not recreate question content locally
unless an offline view is requested. A local iframe may not receive the site's
SameSite-restricted login cookie; use the original-preview window rather than
changing Moodle's security settings.

## Prepare and present

1. Run `moodlectl auth check` from the directory with the intended `.env`; renew with
   `auth login` if necessary. Keep credentials in the native store, not review files.
2. Run `moodlectl review create --view moodle` with the chosen scope and a new output
   directory. Read [references/commands.md](references/commands.md) for examples.
3. Open `review.html` for the instructor. Explain: click **Open Moodle preview** once;
   moving between cards keeps that same preview window on the current question.
   It uses the instructor's browser login, which is separate from the CLI session.
4. Review with **Keep / Needs changes**, swipe or keyboard, undo, and the question
   queue/search. Export the decisions JSON from the final summary after all cards
   are reviewed. Preserve `review.json`; do not infer selections from browser tabs.
5. If Moodle cannot show a preview, resolve browser login/permissions before marking
   that question reviewed. For optional offline exports, check media warnings and
   use Moodle directly for anything missing.

## Choose what happens to the flagged questions

Show the final flagged-question list, then ask what the instructor wants done unless
the exact action has already been specified. Different flags may need different actions.

| Current situation | Appropriate next steps |
| --- | --- |
| No attempts | Propose wording/answer corrections, replace questions, remove fixed questions from the quiz, or exclude questions from random pools. Do not default to full credit or grade previews. |
| Attempts exist | Preserve submissions. Consider correcting an answer key and regrading, a per-response full-credit adjustment, or revising questions for future use. Explain the concrete grading impact before writing grades. |
| Bank-only review | Confirm the destination quiz(s) and whether an edit should affect a shared bank or a separate copy. A bank review does not authorize changing every quiz that uses it. |

For edits, prepare the concrete replacement wording/choices/key for review, respect
existing question versions and verify the saved result. For removal, distinguish
removing a fixed quiz slot from excluding an individual question from a random pool.
Do not delete bank entries or submissions as a shortcut. With random questions,
check the real filters and the number of eligible questions needed for every pool,
including repeated slots and overlapping pools. A random slot is not a question
identity: different students may receive different questions in that position.

The bundled automated write command currently supports **full-credit overrides only**.
Edits, replacements and quiz/pool removals use the site's verified Moodle UI or APIs;
do not invent CLI commands for unsupported actions.

## Full credit only when explicitly chosen

For a schema-2 flag export, run `moodlectl review preview --action full-credit` for an
explicitly identified quiz. Generic review flags alone are not grading authorization.
The command verifies every card decision and the review/site/quiz identity, reads
all attempt-report pages and creates a private before snapshot.

Show selected IDs/names and per-attempt before/after grades. Full credit never lowers
an existing mark, including bonus marks. With multiple attempts, distinguish attempt
totals from the final grade determined by the quiz grading method. Questions never
given to students have no submitted-response adjustment. Finished, numerically graded
attempts are required; explain real blockers rather than bypassing the checks.

After approval of the concrete grading plan (or within prior authorization for that
exact correction), run `moodlectl review apply` with a new journal. Use `--yes` only
when approval already exists. It fetches fresh manual-grading forms, preserves
comments and responses, and verifies each mark and final totals. Already full-credit
responses remain unchanged. Do not change every answer choice to 100%, zero random
slot weights, or delete attempts to unlock quiz editing.

On a partial failure, inspect live results and pending/verified journal records,
then create a fresh preview. Do not automatically replay an interrupted plan.

## Future use and completion

Ask separately each time whether selected questions should also be excluded from
future draws; grade approval does not authorize retirement. If authorized, inspect
versions (including older Ready versions), shared uses and pool capacity before
changing status to Draft or updating pool membership. Verify the resulting eligibility
and unchanged existing grades. `review apply` never changes question status.

Finish with what changed, the selected questions, verification, and—only when grading
was involved—the before/after results. Keep snapshots private. Link the reviewer and
relevant deliverables without exposing credentials or publishing exam/student data.

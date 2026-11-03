---
name: moodle-quiz-question-remediation
description: Guide an instructor through swipe-style review of Moodle quiz or question-bank content, select questions for full credit, preview and apply per-attempt grade corrections after submissions, and separately consider excluding questions from future draws.
---

# Moodle question review and full credit

Use `moodlectl` to give the instructor a visual review of questions, collect their
choices, and award full credit for selected questions while preserving submissions.
This workflow is generic across Moodle sites, courses, question banks and quizzes.
Do not reuse IDs, selections or grading decisions from a previous task.

## Agree on the review

Before exporting, establish the scope with the instructor. Offer useful choices:

- A quiz: its fixed questions, random question pools, and versions used in attempts.
- Attempted questions: only question versions students actually received in a quiz.
- A single bank, or a category (including subcategories) within a bank.
- All available banks in one or several courses, including private quiz banks.
- All accessible courses' question banks. Explain that this may take longer.

Use existing context to identify a course or quiz; ask when the destination is
ambiguous. The default experience is a local swipe-style HTML reviewer, not dozens
of browser tabs. Ask about presentation preferences if the user requests a different
review experience. Selecting a question means **full credit**, not deletion or a
change to its correct answer.

## Export and present

1. Verify the session with `moodlectl auth check` from the directory containing the
   intended `.env`. Use `auth login` if necessary. Keep passwords in the supported
   native credential store, not in the skill, review files or source code.
2. Run `moodlectl review create` with the chosen scope and a new output directory.
   Read [references/commands.md](references/commands.md) for options and examples.
3. Open the generated `review.html` for the user. It contains question text, answer
   choices, correct answers when available, and embedded raster images. It has no
   Moodle write connection and contains no student names or submitted answers.
4. Explain the controls: **Full credit** / **Keep question**, keyboard or swipe,
   undo, queue/search, and a final selection summary. Progress is retained locally.
   The instructor must review all cards before exporting the decisions JSON.
   Keep `review.json` alongside the HTML; do not reconstruct choices from browser
   tabs or infer them from which cards remain open.
5. If the user reports missing media or an unsupported question display, resolve it
   in Moodle before treating that card as reviewed. Check card warnings. Different
   question versions have distinct IDs; do not silently treat a newly edited
   version as the same content students previously received.

## Preview before applying

Obtain the exported decisions JSON (or explicit named choices from the instructor),
then run `moodlectl review preview` for an explicitly identified quiz. A course-wide
selection does not authorize changing every quiz that uses those questions.

Show selected question IDs/names and the per-attempt before/after table, including
how many grades increase, stay unchanged or decrease, and questions never used in
submitted attempts. Full credit should never lower an attempt grade. With multiple
attempts, distinguish attempt totals from the final grade determined by the quiz's
grading method; do not claim every changed attempt changes the gradebook result.

The review is not approval to write grades. If the instructor has already authorized
this exact correction, continue within that authorization; otherwise obtain approval
of the concrete preview before applying. The CLI refuses incomplete/mismatched
selections, unfinished attempts, and changed grading snapshots. Explain a real
blocker rather than bypassing these checks.

## Apply and verify

Run `moodlectl review apply` with the approved plan and a new journal path. Use
`--yes` only when approval is already established. It awards each selected response
its existing maximum mark through the per-attempt manual-grading form. Already
full-credit responses stay unchanged. Correct-answer keys, random-slot weights,
quiz maximum grade and submissions are preserved.

- A randomized quiz position is not a question identity: different students can
  receive different questions in the same slot. Never zero or reweight that slot
  merely because a selected question appeared there.
- Never delete attempts to unlock quiz editing or change all answer choices to
  100% as a workaround. Per-response overrides preserve the question bank's keys.
- The journal records intent before each write and verification after it. If a
  request fails, inspect live results and the journal, then create a fresh preview.
  Do not automatically replay an interrupted plan or reuse an existing journal.
- Verify attempt IDs, responses, unaffected marks, maximum grade and adjusted totals.
  Report the before/after results and keep private snapshots local.

## Ask separately about future use

After grading, ask whether the instructor also wants the selected questions excluded
from future random draws. Grade approval alone does not authorize retirement. The
`review apply` command intentionally does not change question status.

If retirement is authorized, inspect the actual quiz pool filters and question
versions first. Ensure enough eligible questions remain in each pool, accounting
for repeated random slots and overlapping pools. Changing a question to **Draft**
can exclude it from future selection while retaining history; older Ready versions
must also be considered. Do not retire a question if the effect on a shared bank
or pool sufficiency is unclear. Use the Moodle UI's Status column or the installed
version's verified status API; verify statuses and unchanged submitted grades.

## Completion

Summarize selected questions, mark adjustments, affected/unchanged grades and preserved
attempts. State separately whether future exclusion was requested and completed.
Link the local reviewer and relevant private deliverables when appropriate. Avoid
exposing credentials or publishing exam content/student records to a hosted service.

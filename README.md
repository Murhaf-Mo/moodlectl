# moodlectl

Automate your Moodle LMS from the command line.

![CI](https://github.com/Murhaf-Mo/moodlectl/actions/workflows/ci.yml/badge.svg)

Courses, participants, assignments, grading, analytics, bulk content edits — all scriptable. Defaults to the public
sandbox at [school.moodledemo.net](https://school.moodledemo.net) so you can try every command before pointing it at
your own instance.

---

## Install

**Windows** — PowerShell, no Python required:

```powershell
irm https://raw.githubusercontent.com/Murhaf-Mo/moodlectl/master/install.ps1 | iex
```

**macOS** — Terminal, uses Homebrew + pipx:

```bash
curl -fsSL https://raw.githubusercontent.com/Murhaf-Mo/moodlectl/master/install.sh | bash
```

Open a **new** terminal after install so `PATH` is refreshed.

---

## Authenticate

Default URL is `https://school.moodledemo.net`. Skip step 1 to try the demo.

```bash
moodlectl auth set-url https://moodle.yourschool.edu   # optional — point at your own Moodle
moodlectl auth login                                   # opens Chrome, saves session to .env
moodlectl auth check                                   # verify session, show expiry
```

`auth login` skips the browser when the existing session is still valid.

**Manual fallback** — create `.env` in your working directory:

```
MOODLE_BASE_URL=https://school.moodledemo.net
MOODLE_SESSION=<MoodleSession cookie>   # F12 → Application → Cookies
MOODLE_SESSKEY=<sesskey>                # F12 → Network → any service.php body
```

---

## Quick start

Using the demo site, these all work out of the box:

```bash
moodlectl summary                          # upcoming deadlines overview
moodlectl courses list                     # all enrolled courses + IDs
moodlectl courses participants --course 51 # Moodle Mountain roster
moodlectl grades show --course 69          # Mindful Course Creation grades
moodlectl content list --course 51         # activities tree
moodlectl analytics summary --course 69    # full visual report
```

Demo course IDs used below: **51** Moodle Mountain, **69** Mindful Course Creation, **cmid 960** an `assign` module in
course 51.

---

## Commands

### auth

```bash
moodlectl auth set-url https://school.moodledemo.net   # change Moodle URL (once)
moodlectl auth login                                   # browser login
moodlectl auth check                                   # session validity + time left
```

### courses

```bash
moodlectl courses list                                 # id, fullname, shortname

moodlectl courses participants                         # across all courses
moodlectl courses participants --course 51             # one course (--course / --id)
moodlectl courses participants --course 51 --role student
moodlectl courses participants --course 51 --name "Frances"

moodlectl courses inactive                             # students idle 14+ days (default)
moodlectl courses inactive --course 69 --days 30
moodlectl courses inactive --output csv > inactive.csv
```

### grades

```bash
moodlectl grades show                                  # all courses, course-total only
moodlectl grades show --course 69                      # one course
moodlectl grades show --course 69 --full               # every grade item as columns
moodlectl grades show --course 69 --cards              # one panel per student
moodlectl grades show --course 69 --name "Frances"     # filter by student
moodlectl grades show --course 69 --output csv > grades.csv

moodlectl grades stats --course 69                     # mean / median / stdev / min / max
```

### assignments

```bash
moodlectl assignments list                             # cmid + status (active / past)
moodlectl assignments list --course 51 --status active

moodlectl assignments due-soon                         # default: next 7 days
moodlectl assignments due-soon --course 51 --days 14

moodlectl assignments info --assignment 960            # scale, due date, counts
moodlectl assignments submissions --assignment 960 --ungraded

moodlectl assignments ungraded                         # everything waiting to grade
moodlectl assignments ungraded --course 51 --output csv > ungraded.csv

moodlectl assignments missing                          # non-submitters, all assignments
moodlectl assignments missing --assignment 960 --course 51
moodlectl assignments missing --status past            # only overdue

moodlectl assignments remind --assignment 960 --course 51 \
  --text "Reminder: please submit." --dry-run          # preview DMs first
moodlectl assignments remind-all --status active --text "Deadline approaching!" --dry-run

moodlectl assignments download                         # all submitted files
moodlectl assignments download --course 51 --status active --out ./archive
moodlectl assignments download --ungraded              # only files still to grade
moodlectl assignments download --course 51 --user 1542 --user 1481   # specific students
```

Downloads are organised `assignments/COURSE_SHORT/active|past/Assignment_Name/Student_Name_ID/`. Instructor briefs land
in a sibling `_brief/` folder.

### grading

```bash
moodlectl grading show   --assignment 960 --student 48          # current grade + feedback
moodlectl grading submit --assignment 960 --student 48 --grade 10
moodlectl grading submit -a 960 -s 48 -g 8.5 --feedback "Good work overall."
moodlectl grading submit -a 960 -s 48 -g 10 --notify            # email the student

# CSV: user_id,grade,feedback  (feedback column optional)
moodlectl grading batch --assignment 960 --file grades.csv --dry-run
moodlectl grading batch --assignment 960 --file grades.csv
moodlectl grading batch -a 960 -f grades.csv --output csv > results.csv

moodlectl grading next --assignment 960                         # interactive, ungraded only
moodlectl grading next --assignment 960 --notify
```

- `--assignment` → cmid from `assignments list`
- `--student` → user id from `courses participants`
- `--grade` must fit the assignment's scale (see `Grade out of X`)

### analytics

Charts render in-terminal. Pass `--save file.png|pdf` to export.

```bash
moodlectl analytics grades-dist      --course 69                     # histogram
moodlectl analytics grades-dist      --course 69 --item "Midterm Exam"
moodlectl analytics grades-boxplot   --course 69                     # per-assignment spread
moodlectl analytics letter-grades    --course 69                     # A/B/C/D/F bars
moodlectl analytics submission-status --course 69                    # submitted/ungraded/missing
moodlectl analytics grade-progression --course 69                    # mean & median over time
moodlectl analytics at-risk          --course 69 --threshold 70      # below threshold + gaps
moodlectl analytics summary          --course 69 --save-dir ./reports/
```

`--save-dir` writes `1_grade_dist.png`, `2_letter_grades.png`, `3_submission_status.png`, `4_grade_progression.png`.

### content

Manage sections and modules of any type (resource, url, page, forum, quiz, assign, label, …).

```bash
moodlectl content list   --course 51                     # tree view
moodlectl content list   --course 51 --section 4         # one section (0-indexed)
moodlectl content list   --course 51 --type assign       # filter by module type
moodlectl content list   --course 51 --no-hidden
moodlectl content list   --course 51 --output json

moodlectl content show   --course 51 --cmid 960          # one module's details
moodlectl content hide   --course 51 --cmid 960
moodlectl content unhide --course 51 --cmid 960
moodlectl content rename --course 51 --cmid 960 --name "Alpine Night — Kit List"
moodlectl content delete --course 51 --cmid 960 --force  # → Moodle recycle bin

moodlectl content section hide   --course 51 --section 1
moodlectl content section unhide --course 51 --section 1
moodlectl content section rename --course 51 --section 1 --name "Week 1: Introduction"

moodlectl content settings --course 51 --cmid 960        # all editable fields
moodlectl content set      --course 51 --cmid 960 --field due_date   --value "2026-05-01 23:59"
moodlectl content set      --course 51 --cmid 960 --field max_grade  --value 20
moodlectl content set      --course 51 --cmid 960 --field description --value "<p>Updated.</p>"

moodlectl content create --course 83 --section 1 --type label --set content='<p>Week 1</p>'
moodlectl content create --course 83 --section 2 --type url --name "Syllabus" --set external_url=https://example.com
moodlectl content create --course 83 --section 3 --type assign --name "Homework 1" --set due_date="2026-06-01 23:59" --set grading_due="2026-06-08 23:59" --set max_grade=10
moodlectl content create --course 83 --section 9 --type resource --file "CH6.pdf"  # upload a local file
moodlectl content create --course 83 --from-yaml new_modules.yaml   # bulk create

moodlectl content download --cmid 19905                              # download a resource file
moodlectl content download --cmid 19905 --cmid 20194 --out ./pdfs    # multiple, into a folder
```

`--set key=value` is repeatable and accepts any field from `content settings`. `--name` is required for every type
except `label` (and `resource` when `--file` is given — the filename is used). New modules are appended to the target
section — use `content push` afterwards to reorder.

`--file` uploads a local file into the resource's draft area before the module is created. Only valid for `resource`.

**Editable fields by type:**

| Type       | Fields                                                                                                        |
|------------|---------------------------------------------------------------------------------------------------------------|
| `assign`   | `description`, `due_date`, `available_from`, `cut_off`, `max_grade`, `grade_pass`                             |
| `quiz`     | `description`, `due_date`, `available_from`, `cut_off`, `time_limit_mins`, `attempts_allowed`, `grade_method` |
| `forum`    | `description`, `subscription_mode`, `max_attachments`                                                         |
| *(others)* | `description`                                                                                                 |

Dates use `"YYYY-MM-DD HH:MM"`.

**Bulk edit via YAML** — export the whole course, edit in any text editor, push back:

```bash
moodlectl content pull --course 51 -o course.yaml
moodlectl content push course.yaml --dry-run     # preview the diff
moodlectl content push course.yaml               # prompts to confirm
moodlectl content push course.yaml --yes         # apply without prompt
```

Each module gets a `settings:` block with every editable field for its type. Only changed values are pushed. Reorder
entries in the YAML to reorder modules/sections. Modules removed from the YAML are flagged but never auto-deleted.

**Add modules via YAML** — drop an entry into any section with no `cmid` (push will create it):

```yaml
- type: url           # required
  name: New link      # required except for label
  settings:
    external_url: https://example.com

- type: resource                             # upload a local file
  name: Chapter 6 — SQL syntax               # optional; defaults to the filename
  file: C:\Users\me\Downloads\CH6.pdf        # absolute path on your machine
```

Works both in `content push` (alongside edits/reorders) and standalone via `content create --from-yaml`. Accepts either
a single mapping or a list; top-level `section: <n>` is required when the file is consumed by `content create`, inferred
from position when consumed by `content push`.

### announcements

Post, view, edit, and delete discussions in a course forum. Posts in the default
Announcements (news) forum email every enrolled student and hit the dashboard
alert — same behaviour as the Moodle web UI.

```bash
moodlectl announcements send -c 51 -s "Midterm moved" -m "<p>Thursday 10 am.</p>"
moodlectl announcements send -c 51 -s "Week 6 notes" --message-file week6.html --pinned
moodlectl announcements send --forum 19850 -s "..." -m "..." --no-mail
moodlectl announcements send -c 51 -s "Syllabus" -m "<p>See attached.</p>" --attach syllabus.pdf
moodlectl announcements send -c 51 -s "Notes" --message-file notes.md --format markdown

moodlectl announcements list -c 51                 # newest first, pinned surface above
moodlectl announcements list --forum 19850 --limit 5 -o json

moodlectl announcements show   --id 2456           # root post + replies
moodlectl announcements edit   --id 2456 -s "Corrected date" --message-file fix.html
moodlectl announcements delete --id 2456 --force
```

`--course`/`-c` auto-resolves the course's news forum. `--forum <cmid>` targets
any other forum (copy the cmid from `content list`). `--message` accepts raw
HTML; `--message-file` reads from a local file (convenient for long RTL Arabic
notes). `--format` switches between `html` (default), `plain`, `moodle`, and
`markdown`. `--attach` is repeatable — each file is uploaded to a fresh draft
area and attached to the discussion. `--no-mail` suppresses the instant email
blast while still publishing the post. `--pinned` sticks the discussion to the
top. `--group <id>` restricts the post to a specific group (`-1` = all).

`edit` rewrites only the root post's subject and message; other metadata
(mail-now, pinned, attachments) is left as-is. `delete` removes the root post,
which cascades to every reply.

### questions

Import a Moodle XML question bank into a course's question bank. Validates
the XML locally first (parses, counts questions per type, lists categories),
runs a remote pre-flight (session valid, import form reachable), then prompts
for confirmation. Strict mode: any warning or error reported by Moodle aborts.

```bash
moodlectl questions import --course 581 --file quiz.xml --dry-run   # local validation only
moodlectl questions import -c 581 -f quiz.xml                       # prompt then upload
moodlectl questions import -c 581 -f quiz.xml --yes                 # skip prompt
```

The XML can contain `<question type="category">` entries — they're honoured
on import (`catfromfile=1`, `contextfromfile=1`), so categories and contexts
declared in the file are created automatically. Only Moodle XML is supported;
GIFT, Aiken, etc. are not yet wired in.

### messages

```bash
moodlectl messages send --to 48 --text "Your assignment is due tomorrow."
moodlectl messages delete --id 98765
```

### Output formats

All commands accept `--output` / `-o`:

```
table   # default, pretty terminal table
json    # machine-readable array
csv     # UTF-8 with BOM, opens cleanly in Excel
```

---

## Typical workflows

**Morning check:**

```bash
moodlectl auth check
moodlectl summary
moodlectl assignments due-soon --days 3
```

**Grading session:**

```bash
moodlectl assignments ungraded --course 51
moodlectl grading next --assignment 960                 # or:
moodlectl grading batch --assignment 960 --file grades.csv --dry-run
moodlectl grading batch --assignment 960 --file grades.csv
```

**Chase late submissions:**

```bash
moodlectl assignments missing --assignment 960 --course 51
moodlectl assignments remind  --assignment 960 --course 51 --text "Deadline is Friday."
```

**End-of-term export:**

```bash
moodlectl grades show --course 69 --output csv > grades.csv
moodlectl assignments missing --output csv > missing.csv
moodlectl grades stats --course 69
```

**Bulk content edit:**

```bash
moodlectl content pull --course 51 -o course.yaml
# edit: rename, hide/unhide, reorder, change due dates, grade limits, …
moodlectl content push course.yaml --dry-run
moodlectl content push course.yaml --yes
```

**Analytics report:**

```bash
moodlectl analytics summary       --course 69 --save-dir ./reports/
moodlectl analytics at-risk       --course 69
moodlectl analytics letter-grades --course 69
```

---

## For developers

```bash
git clone https://github.com/Murhaf-Mo/moodlectl
cd moodlectl
pip install -e ".[dev,analytics,browser]"

cp .env.example .env   # fill in MOODLE_SESSION and MOODLE_SESSKEY

pytest
ruff check .
```

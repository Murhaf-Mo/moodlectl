# moodlectl

Automate your Moodle LMS from the command line. Built for CCK University instructors.

---

## Setup

**1. Install**

```bash
pip install -e .                          # core only
pip install -e ".[analytics]"             # + terminal & PNG chart support
pip install -e ".[export]"                # + Excel export
pip install -e ".[analytics,export]"      # everything
```

**2. Configure credentials**

Copy `.env.example` to `.env` and fill in your values:

```
MOODLE_BASE_URL=https://mylms.cck.edu.kw
MOODLE_SESSION=
MOODLE_SESSKEY=
```

To get your session values — log into Moodle in your browser, then:

- `MOODLE_SESSION` → F12 → **Application** → **Cookies** → copy `MoodleSession` value
- `MOODLE_SESSKEY` → F12 → **Network** → click any request to `service.php` → look in the request body for `sesskey`

> Sessions expire when you close your browser. Paste fresh values into `.env` to reconnect.

---

## Quick start

```bash
moodlectl summary                   # upcoming deadlines at a glance
moodlectl auth check                # verify your session before long operations
moodlectl courses list              # see your course IDs
moodlectl assignments list          # see assignment cmids
moodlectl assignments ungraded      # everything waiting to be graded
```

---

## Commands

### auth

```bash
# Verify your session is still active before running long commands
moodlectl auth check
```

### courses

```bash
# List all your enrolled courses (shows course IDs)
moodlectl courses list

# All participants across all courses
moodlectl courses participants

# Single course — --course and --id are aliases
moodlectl courses participants --course 568
moodlectl courses participants --id 568

# Filter by role or name (partial match)
moodlectl courses participants --course 568 --role student
moodlectl courses participants --course 568 --name "Ali"

# Students who haven't logged in for 14+ days (default) — all courses
moodlectl courses inactive
moodlectl courses inactive --days 7

# Limit to a single course
moodlectl courses inactive --course 568
moodlectl courses inactive --course 568 --days 7
moodlectl courses inactive --output csv > inactive.csv
```

### grades

```bash
# Summary: name + course total (default, all courses)
moodlectl grades show
moodlectl grades show --course 568

# Wide table: all grade items as columns
moodlectl grades show --course 568 --full

# Cards: one panel per student with all grade items
moodlectl grades show --course 568 --cards

# Filter to a specific student (partial name match)
moodlectl grades show --course 568 --name "Aljawhara"
moodlectl grades show --course 568 --name "Aljawhara" --cards

# Export all grade columns to CSV (opens correctly in Excel)
moodlectl grades show --course 568 --output csv > grades.csv

# Grade statistics: mean, median, std dev, min, max for the course total
moodlectl grades stats --course 568
```

### assignments

```bash
# List all assignments across all courses (shows cmid, status: active / past)
moodlectl assignments list
moodlectl assignments list --status active
moodlectl assignments list --course 568 --status past

# Assignments due in the next N days (default: 7), sorted most urgent first
moodlectl assignments due-soon
moodlectl assignments due-soon --days 3
moodlectl assignments due-soon --course 568 --days 14

# Full details for one assignment (cmid, grade scale, due date, submission count)
moodlectl assignments info --assignment 18002

# List who submitted and which files — no downloads
moodlectl assignments submissions --assignment 18002
moodlectl assignments submissions --assignment 18002 --output csv > submitted.csv

# Only show submissions that haven't been graded yet
moodlectl assignments submissions --assignment 18002 --ungraded

# Show all submitted-but-ungraded work across every course
moodlectl assignments ungraded
moodlectl assignments ungraded --status past
moodlectl assignments ungraded --course 590
moodlectl assignments ungraded --output csv > ungraded.csv

# Show students who have NOT submitted
# Single assignment:
moodlectl assignments missing --assignment 18002 --course 568
# All assignments (bulk scan):
moodlectl assignments missing
moodlectl assignments missing --status past       # only overdue
moodlectl assignments missing --status active     # only upcoming
moodlectl assignments missing --course 568
moodlectl assignments missing --output csv > missing.csv

# Send a Moodle message to everyone who hasn't submitted a single assignment
moodlectl assignments remind --assignment 18002 --course 568 --text "Reminder: please submit your work."
moodlectl assignments remind --assignment 18002 --course 568 --text "..." --dry-run

# Bulk remind across all courses and assignments
moodlectl assignments remind-all --text "You have pending submissions."
moodlectl assignments remind-all --status active --text "Deadline approaching!" --dry-run
moodlectl assignments remind-all --course 568 --text "..."

# Download all submitted files (organised by course / active|past / assignment / student)
moodlectl assignments download
moodlectl assignments download --course 568 --status active
moodlectl assignments download --course 568 --status past --out ./archive

# Download only submissions that haven't been graded yet
moodlectl assignments download --ungraded
moodlectl assignments download --course 568 --ungraded
```

Downloaded files are organised as:

```
assignments/
  COURSE_SHORT/
    active/
      Assignment_Name/
        _brief/               ← instructor-attached brief files
        Student_Name_123/
          submission.pdf
    past/
      Assignment_Name/
        Student_Name_456/
          report.docx
```

### grading

```bash
# Check the current grade and feedback before overwriting
moodlectl grading show --assignment 18002 --student 1557

# Submit a grade
moodlectl grading submit --assignment 18002 --student 1557 --grade 10

# With written feedback
moodlectl grading submit -a 18002 -s 1557 -g 8.5 --feedback "Good work overall."

# Notify the student by email after grading
moodlectl grading submit -a 18002 -s 1557 -g 10 --notify

# Grade all students from a CSV file
# CSV format: user_id,grade,feedback (header required; feedback column is optional)
moodlectl grading batch --assignment 18002 --file grades.csv --dry-run   # preview first
moodlectl grading batch --assignment 18002 --file grades.csv
moodlectl grading batch -a 18002 -f grades.csv --output csv > results.csv

# Guided grading: work through all ungraded students interactively
moodlectl grading next --assignment 18002
moodlectl grading next --assignment 18002 --notify
```

ID reference:

- `--assignment` is the cmid from `moodlectl assignments list`
- `--student` is the user ID from `moodlectl courses participants`
- `--grade` must be within the assignment's configured grade scale (shown as "Grade out of X")

### analytics

> Requires `pip install -e ".[analytics]"` (plotext + matplotlib).

Charts render directly in your terminal by default. Pass `--save <file>` to write a PNG or PDF instead.

```bash
# Grade distribution histogram — spot bimodal curves, decide whether to norm-reference
moodlectl analytics grades-dist --course 568
moodlectl analytics grades-dist --course 568 --save dist.png
moodlectl analytics grades-dist --course 568 --save dist.pdf --fmt pdf

# Filter to a specific grade item instead of Course Total
moodlectl analytics grades-dist --course 568 --item "Midterm Exam"

# Box plot — compare grade spread across assignments; find the hardest one
moodlectl analytics grades-boxplot --course 568
moodlectl analytics grades-boxplot --course 568 --save boxplot.png

# Letter grade bar chart (A / B / C / D / F)
# grade-max is auto-detected from the report — no flag needed for non-100 scales
moodlectl analytics letter-grades --course 568
moodlectl analytics letter-grades --course 568 --save letters.png

# Submission status — submitted / ungraded / missing per assignment
moodlectl analytics submission-status --course 568
moodlectl analytics submission-status --course 568 --assignment-id 18002  # single assignment
moodlectl analytics submission-status --course 568 --save status.png

# Grade progression — mean & median line chart across assignments in grade-report order
moodlectl analytics grade-progression --course 568
moodlectl analytics grade-progression --course 568 --save progress.png

# At-risk students — below threshold AND/OR have missing/ungraded work
# --threshold is a percentage of the course max (default 60%)
# action column: "remind" | "grade" | "both"
moodlectl analytics at-risk --course 568
moodlectl analytics at-risk --course 568 --threshold 70

# Full report — all charts in one command; optionally save all as PNGs
moodlectl analytics summary --course 568
moodlectl analytics summary --course 568 --save-dir ./reports/
```

`--save-dir` layout:

```
reports/
  1_grade_dist.png
  2_letter_grades.png
  3_submission_status.png
  4_grade_progression.png
```

### messages

```bash
# Send a direct message (use student ID from `courses participants`)
moodlectl messages send --to 1557 --text "Your assignment is due tomorrow."

# Delete (unsend) a message
moodlectl messages delete --id 98765
```

### Output formats

All commands support `--output` / `-o`:

```bash
--output table    # default — pretty table in the terminal
--output json     # machine-readable JSON array
--output csv      # UTF-8 CSV, opens correctly in Excel
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
moodlectl assignments ungraded --course 568          # see what needs grading
moodlectl grading next --assignment 18002            # grade interactively
# or
moodlectl grading batch --assignment 18002 --file grades.csv --dry-run
moodlectl grading batch --assignment 18002 --file grades.csv
```

**Chase late submissions:**

```bash
moodlectl assignments missing --assignment 18002 --course 568
moodlectl assignments remind --assignment 18002 --course 568 --text "Deadline is Friday."
```

**End of term export:**

```bash
moodlectl grades show --course 568 --output csv > grades.csv
moodlectl assignments missing --output csv > missing.csv
moodlectl grades stats --course 568
```

**Course analytics report:**

```bash
# Full visual report saved to disk — share with department or keep for records
moodlectl analytics summary --course 568 --save-dir ./reports/

# Or run individual charts as needed
moodlectl analytics at-risk --course 568               # who needs attention right now
moodlectl analytics letter-grades --course 568          # A/B/C/D/F breakdown
moodlectl analytics grade-progression --course 568      # is the cohort improving?
```

# moodlectl

Automate your Moodle LMS from the command line. Built for CCK University instructors.

## Setup

**1. Install**
```bash
pip install -e .
```

**2. Configure credentials**

Copy `.env.example` to `.env` and fill in your values:
```
MOODLE_BASE_URL=https://mylms.cck.edu.kw
MOODLE_SESSION=
MOODLE_SESSKEY=
ANTHROPIC_API_KEY=        # only needed for AI features (coming soon)
```

To get your session values — log into Moodle in your browser, then:
- `MOODLE_SESSION` → F12 → **Application** → **Cookies** → copy `MoodleSession` value
- `MOODLE_SESSKEY` → F12 → **Network** → click any request to `service.php` → look in the request body for `sesskey`

> These expire when you close your browser. Paste fresh values into `.env` to reconnect.

---

## Commands

### Courses

```bash
# List all your courses (shows course IDs)
moodlectl courses list

# All participants across all courses
moodlectl courses participants

# Single course
moodlectl courses participants --id 568

# Filter by role or name (partial match)
moodlectl courses participants --id 568 --role student
moodlectl courses participants --id 568 --name "Ali"
```

### Grades

```bash
# Summary: name + course total (default for all courses)
moodlectl grades show
moodlectl grades show --course 568

# Wide table: all grade items in one table
moodlectl grades show --course 568 --full

# Cards: one panel per student with all grade items
moodlectl grades show --course 568 --cards

# Filter to a specific student (partial name match)
moodlectl grades show --course 568 --name "Aljawhara"
moodlectl grades show --course 568 --name "Aljawhara" --cards

# Export all grade columns to CSV (opens correctly in Excel)
moodlectl grades show --course 568 --output csv > grades.csv
```

### Assignments

```bash
# List all assignments across all courses (shows cmid, status: active / past)
moodlectl assignments list
moodlectl assignments list --status active
moodlectl assignments list --course 568 --status past

# List who submitted and which files — no downloads
moodlectl assignments submissions --assignment 18002
moodlectl assignments submissions --assignment 18002 --output csv > submitted.csv

# Show students who have NOT submitted (with their last access time)
moodlectl assignments missing --assignment 18002 --course 568
moodlectl assignments missing --assignment 18002 --course 568 --output csv > missing.csv

# Download all submitted files (organised by course / active|past / assignment / student)
moodlectl assignments download
moodlectl assignments download --course 568 --status active
moodlectl assignments download --course 568 --status past --out ./archive
```

Downloaded files are organised as:
```
assignments/
  COURSE_SHORT/
    active/
      Assignment_Name/
        Student_Name_123/
          submission.pdf
    past/
      Assignment_Name/
        Student_Name_456/
          report.docx
```

### Grading

```bash
# Check the current grade and feedback before overwriting
moodlectl grading show-grade --assignment 18002 --student 1557

# Submit a grade
moodlectl grading submit --assignment 18002 --student 1557 --grade 10

# With written feedback
moodlectl grading submit -a 18002 -s 1557 -g 8.5 --feedback "Good work overall."

# Notify the student by email after grading
moodlectl grading submit -a 18002 -s 1557 -g 10 --notify
```

- `--assignment` is the cmid from `moodlectl assignments list`
- `--student` is the user ID from `moodlectl courses participants`
- `--grade` must be within the assignment's configured grade scale (shown as "Grade out of X" in Moodle)

### Messages

```bash
# Send a direct message (use student ID from `courses participants`)
moodlectl messages send --to 1557 --text "Your assignment is due tomorrow."

# Delete (unsend) a message
moodlectl messages delete --id 98765
```

### Output formats

All commands support `--output` / `-o`:

```bash
--output table    # default — pretty table
--output json     # machine-readable JSON
--output csv      # UTF-8 CSV, opens correctly in Excel
```

---

## Coming Soon

- `moodlectl reports student` — full report per student across all courses
- `moodlectl ai grade` — AI-powered assignment grading via Claude (reads downloaded files)
- `moodlectl ai reply` — auto-reply to student messages

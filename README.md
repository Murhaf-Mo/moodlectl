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
moodlectl courses participants --id 568 --role teacher
moodlectl courses participants --id 568 --name "Ali"
```

### Grades

```bash
# Summary: name + course total
moodlectl grades show --course 568

# Full detail: one panel per student with every grade item
moodlectl grades show --course 568 --full

# Filter to specific students
moodlectl grades show --course 568 --name "Abdulrahman"
moodlectl grades show --course 568 --full --name "Ali"

# Export all grade columns to CSV (opens correctly in Excel)
moodlectl grades show --course 568 --output csv > grades.csv
```

### Assignments

```bash
# List all assignments across all courses (shows status: active / past)
moodlectl assignments list

# Filter by status
moodlectl assignments list --status active
moodlectl assignments list --status past

# Specific courses only
moodlectl assignments list --course 568 --course 570

# Download all submitted files (organised by course / active|past / assignment / student)
moodlectl assignments download

# Download only active assignments for a specific course
moodlectl assignments download --course 568 --status active

# Choose a custom output directory
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
# Submit a grade for a student on an assignment
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
moodlectl messages send --to 1557 --text "Your assignment is due tomorrow"
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

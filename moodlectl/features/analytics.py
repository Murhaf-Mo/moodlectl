"""Data aggregation for the analytics command group.

Bridges existing client/feature functions into the shapes that output/charts.py expects.
No HTTP calls are made directly — all data comes through MoodleClientProtocol methods.
"""
from __future__ import annotations

import re

from moodlectl.features.assignments import is_ungraded
from moodlectl.types import (
    AssignmentGrades,
    AtRiskStudent,
    Cmid,
    CourseId,
    MoodleClientProtocol,
    Participant,
    Submission,
    SubmissionSummary,
    UserId,
)

# Matches the leading float in Moodle grade strings like "75.00 (75.00 %)" or "10.00"
_GRADE_RE = re.compile(r"([\d.]+)")


def _parse_grade(raw: object) -> float | None:
    """Extract the leading float from a Moodle grade string, or return None."""
    m = _GRADE_RE.match(str(raw))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def get_grade_distribution(
        client: MoodleClientProtocol,
        course_id: CourseId,
        grade_item: str | None = None,
) -> tuple[list[float], str]:
    """Return (grades, column_name) for a single grade item in the course.

    grade_item: exact column name to use. None → last column (Course total).
    Rows with non-numeric values (e.g. "-") are silently excluded.
    """
    report = client.get_grade_report(course_id)
    columns = report["columns"]
    rows = report["rows"]

    col = grade_item if grade_item is not None else (columns[-1] if columns else "")

    grades: list[float] = []
    for row in rows:
        v = _parse_grade(row.get(col, "-"))
        if v is not None:
            grades.append(v)

    return grades, col


def get_per_assignment_grades(
        client: MoodleClientProtocol,
        course_id: CourseId,
) -> list[AssignmentGrades]:
    """Return one AssignmentGrades entry per grade-item column (excluding Course total).

    Columns with zero numeric values are omitted — they carry no analytical signal.
    """
    report = client.get_grade_report(course_id)
    columns = report["columns"]
    rows = report["rows"]

    # The last column is always "Course total" — skip it for per-assignment breakdown
    item_columns = columns[:-1] if len(columns) > 1 else columns

    results: list[AssignmentGrades] = []
    for col in item_columns:
        grades: list[float] = []
        for row in rows:
            v = _parse_grade(row.get(col, "-"))
            if v is not None:
                grades.append(v)
        if grades:
            results.append({"assignment": col, "grades": grades})

    return results


def get_submission_summary(
        client: MoodleClientProtocol,
        course_id: CourseId,
) -> list[SubmissionSummary]:
    """Return submission state counts per assignment for a course.

    For each assignment:
      - submitted: students with at least one file on record
      - ungraded:  submitted entries where grading_status has no digits
      - missing:   enrolled students minus submitted (approximated from participant list)
      - total:     submitted + missing
    """
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn

    console = Console(stderr=True)
    assignments = client.get_course_assignments(course_id)

    try:
        participants = client.get_course_participants(course_id)
        student_count = sum(
            1 for p in participants if "student" in p.get("roles", "").lower()
        )
    except Exception:
        student_count = 0

    results: list[SubmissionSummary] = []

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console) as progress:
        task = progress.add_task("Fetching submissions…", total=len(assignments))

        for assign in assignments:
            cmid: Cmid = assign["cmid"]
            progress.update(task, description=f"[cyan]{assign['name'][:50]}[/cyan]")

            # Skip assignments with no submissions — they haven't been opened yet
            # (future quizzes, unreleased assignments). Including them would show
            # every student as "missing" for work they can't see yet.
            if assign["submitted_count"] == 0:
                progress.advance(task)
                continue

            try:
                subs: list[Submission] = client.get_assignment_submissions(cmid)
            except Exception:
                progress.advance(task)
                continue

            submitted = len(subs)
            ungraded = sum(1 for s in subs if is_ungraded(s))
            missing = max(0, student_count - submitted)

            results.append({
                "cmid": cmid,
                "name": assign["name"],
                "submitted": submitted,
                "ungraded": ungraded,
                "missing": missing,
                "total": submitted + missing,
            })
            progress.advance(task)

    return results


def get_at_risk_students(
        client: MoodleClientProtocol,
        course_id: CourseId,
        threshold: float = 60.0,
) -> list[AtRiskStudent]:
    """Return students who may need instructor attention.

    A student is at-risk if their Course total is below `threshold` OR they have
    missing submissions OR they have ungraded submissions.

    action field:
      "remind" — has missing submissions (should submit)
      "grade"  — has ungraded submissions (instructor should grade)
      "both"   — both of the above
      "" (empty) — only below-threshold with no submission issues
    """
    report = client.get_grade_report(course_id)
    columns = report["columns"]
    total_col = columns[-1] if columns else ""

    # Build a grade lookup: user_id → course total float
    grade_lookup: dict[int, float | None] = {}
    for row in report["rows"]:
        uid_raw = row.get("id")
        if uid_raw is None:
            continue
        uid = int(uid_raw)
        grade_lookup[uid] = _parse_grade(row.get(total_col, "-"))

    # Submission state per student across all assignments
    missing_counts: dict[int, int] = {}
    ungraded_counts: dict[int, int] = {}

    try:
        participants = client.get_course_participants(course_id)
        student_ids: set[int] = {
            p["id"] for p in participants
            if "student" in p.get("roles", "").lower()
        }
    except Exception:
        student_ids = set(grade_lookup.keys())

    for sid in student_ids:
        missing_counts[sid] = 0
        ungraded_counts[sid] = 0

    assignments = client.get_course_assignments(course_id)
    for assign in assignments:
        # Skip assignments nobody has touched — these are future/unreleased work,
        # not assignments where every student is delinquent.
        if assign["submitted_count"] == 0:
            continue

        try:
            subs = client.get_assignment_submissions(assign["cmid"])
        except Exception:
            continue

        submitted_ids = {s["user_id"] for s in subs}
        for sid in student_ids:
            if sid not in submitted_ids:
                missing_counts[sid] = missing_counts.get(sid, 0) + 1

        for sub in subs:
            if is_ungraded(sub):
                uid = sub["user_id"]
                ungraded_counts[uid] = ungraded_counts.get(uid, 0) + 1

    # Build participant lookup for name/email
    try:
        p_lookup = {p["id"]: p for p in participants}  # type: ignore[possibly-undefined]
    except Exception:
        p_lookup = {}

    results: list[AtRiskStudent] = []
    for sid in student_ids:
        ct = grade_lookup.get(sid)
        mc = missing_counts.get(sid, 0)
        uc = ungraded_counts.get(sid, 0)

        below = ct is not None and ct < threshold
        if not (below or mc > 0 or uc > 0):
            continue

        if mc > 0 and uc > 0:
            action = "both"
        elif mc > 0:
            action = "remind"
        elif uc > 0:
            action = "grade"
        else:
            action = ""

        p: Participant | None = p_lookup.get(UserId(sid))
        results.append({
            "user_id": UserId(sid),
            "fullname": p["fullname"] if p is not None else f"User {sid}",
            "email": p["email"] if p is not None else "",
            "course_total": ct,
            "missing_count": mc,
            "ungraded_count": uc,
            "action": action,
        })

    results.sort(key=lambda r: (r["course_total"] is None, r["course_total"] or 0.0))
    return results

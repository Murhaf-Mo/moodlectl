"""Shared TypedDict definitions, type aliases, NewTypes, and the client Protocol.

All public API shapes live here so every layer (client, features, CLI) agrees
on the exact structure of each object without using Any.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, NewType, Protocol, TypedDict

# ---------------------------------------------------------------------------
# Semantic ID types — prevents mixing up cmid, user_id, and course_id
# ---------------------------------------------------------------------------

Cmid = NewType("Cmid", int)
"""Course-module ID — identifies a course module (from course/view.php data-id)."""

UserId = NewType("UserId", int)
"""Moodle user ID — identifies a student or teacher (from `user/index.php`)."""

CourseId = NewType("CourseId", int)
"""Moodle course ID — identifies a course (from enrolled courses API)."""

SectionId = NewType("SectionId", int)
"""Moodle section DB id — NOT the ordinal section number. Used in API calls."""

# ---------------------------------------------------------------------------
# Recursive JSON type — used only at the raw HTTP boundary in client/base.py
# ---------------------------------------------------------------------------

type JSON = str | int | float | bool | None | dict[str, JSON] | list[JSON]

# ---------------------------------------------------------------------------
# Constrained string aliases
# ---------------------------------------------------------------------------

type AssignmentStatus = Literal["active", "past", "all"]
"""Status filter for assignment queries. Individual assignments use only "active" | "past"."""

type OutputFmt = Literal["table", "json", "csv"]
"""Output format accepted by print_table()."""


# ---------------------------------------------------------------------------
# Client layer — shapes returned directly by MoodleAPI methods
# ---------------------------------------------------------------------------

class Course(TypedDict):
    id: CourseId
    fullname: str
    shortname: str
    visible: int
    enddate: int


class FileRef(TypedDict):
    filename: str
    url: str


class CourseModule(TypedDict):
    cmid: Cmid
    name: str
    modname: str  # "forum", "resource", "label", "url", "page", "assign", …
    visible: bool
    url: str  # deeplink to activity page (empty string if absent)
    description: str  # inline description shown on the course page (empty if absent)
    due_date: str  # due date string for assign/quiz (empty for other types)
    settings: dict[str, Any]  # curated per-type settings (empty unless fetch_settings=True)


class CourseSection(TypedDict):
    id: SectionId  # DB id — used in API calls, not shown to users
    number: int  # ordinal 0-indexed position — shown to users
    name: str
    summary: str  # section description/summary (empty if absent)
    visible: bool
    modules: list[CourseModule]


class Participant(TypedDict):
    id: UserId
    fullname: str
    email: str
    roles: str
    lastaccess: str
    status: str


class AssignmentMeta(TypedDict):
    """Raw assignment row scraped from /mod/assign/index.php."""
    cmid: Cmid
    name: str
    due_text: str
    submitted_count: int


class Submission(TypedDict):
    user_id: UserId
    fullname: str
    email: str
    status: str
    grading_status: str
    files: list[FileRef]


class GradeReport(TypedDict):
    columns: list[str]
    # Grade rows have fixed keys (id, fullname, email) plus one dynamic key per
    # grade item — all values are strings or ints, never nested.
    rows: list[dict[str, str | int]]


# Grade form fields are completely dynamic (HTML form element names).
# All values are strings; the special __grade_max__ key is added by the client.
FormFields = dict[str, str]

# ---------------------------------------------------------------------------
# Convenience aliases used across multiple layers
# ---------------------------------------------------------------------------

type CourseMap = dict[CourseId, Course]
"""Keyed-by-ID course lookup — built from get_courses() results."""


# ---------------------------------------------------------------------------
# Feature layer — shapes produced by features/ business-logic functions
# ---------------------------------------------------------------------------

class AssignmentListing(TypedDict):
    """Assignment enriched with parsed due-date and status, from list_assignments()."""
    course_id: CourseId
    cmid: Cmid
    name: str
    due_text: str
    due_dt: datetime | None
    submitted_count: int
    status: Literal["active", "past"]


class MissingStudent(TypedDict):
    """Student who has not submitted a given assignment."""
    user_id: UserId
    fullname: str
    email: str
    lastaccess: str


class MissingResult(TypedDict):
    """Row from get_all_missing_submissions() — includes course and assignment context."""
    course: str
    assignment: str
    assignment_status: str
    due_date: str
    user_id: UserId
    fullname: str
    email: str
    lastaccess: str


class UngradedResult(TypedDict):
    """Row from get_all_ungraded_submissions()."""
    course: str
    assignment: str
    assignment_status: str
    due_date: str
    user_id: UserId
    fullname: str
    email: str
    grading_status: str
    files: str  # comma-joined filenames for display


class DueSoon(TypedDict):
    """Assignment due within N days, from get_due_soon()."""
    course: str
    cmid: Cmid
    assignment: str
    due_date: str
    submitted: int
    days_left: int


class DownloadResult(TypedDict):
    """Per-student download summary from download_submissions()."""
    course: str
    assignment: str
    student: str
    student_id: UserId
    files_ok: int
    files_err: int
    path: str


class ReminderResult(TypedDict):
    """Result of remind_missing_students() — one row per student."""
    user_id: UserId
    fullname: str
    email: str
    lastaccess: str
    sent: bool


class BulkReminderResult(TypedDict):
    """Result of remind_all_missing_students() — includes course and assignment."""
    course: str
    assignment: str
    user_id: UserId
    fullname: str
    sent: bool


class InactiveStudent(TypedDict):
    """Single-course inactive student row (no course column)."""
    user_id: UserId
    fullname: str
    email: str
    lastaccess: str
    inactive_days: int | str  # "?" when lastaccess text is unparseable


class CourseInactiveStudent(TypedDict):
    """All-courses inactive student row (includes course shortname)."""
    course: str
    user_id: UserId
    fullname: str
    email: str
    lastaccess: str
    inactive_days: int | str  # "?" when lastaccess text is unparseable


class GradeResult(TypedDict):
    """Returned by features/grading.submit_grade()."""
    user_id: UserId
    grade: float
    grade_max: float
    grade_pct: float | None
    feedback: str


class BatchResult(TypedDict):
    """One row from features/grading.batch_grade()."""
    user_id: UserId
    grade: float
    grade_max: float | str  # "?" when submission raised an error
    grade_pct: float | None
    ok: bool | str  # True | False | "(dry run)"
    error: str


class GradeStats(TypedDict):
    """Output of features/grades.compute_stats(). count=0 means no numeric grades found."""
    column: str
    count: int
    mean: float
    median: float
    std_dev: float
    min: float
    max: float


class AssignmentGrades(TypedDict):
    """Per-assignment grade list — one entry per grade-item column in the grade report."""
    assignment: str  # grade item column name (e.g. "Assignment 1")
    grades: list[float]  # one float per student who has a numeric grade


class SubmissionSummary(TypedDict):
    """Counts of submission states for one assignment."""
    cmid: Cmid
    name: str
    submitted: int  # has at least one uploaded file
    ungraded: int  # submitted but grading_status has no digits
    missing: int  # enrolled students with no submission on record
    total: int  # submitted + missing (enrolled student count)


class AtRiskStudent(TypedDict):
    """Student who may need instructor attention."""
    user_id: UserId
    fullname: str
    email: str
    course_total: float | None  # None when the grade report row has no numeric value yet
    missing_count: int  # assignments with no file submission
    ungraded_count: int  # submissions awaiting a grade
    action: str  # "remind" | "grade" | "both"


# ---------------------------------------------------------------------------
# Client Protocol — features depend on this, not on the concrete MoodleAPI class
# ---------------------------------------------------------------------------

class MoodleClientProtocol(Protocol):
    """Structural interface that MoodleAPI satisfies.

    Feature functions accept this Protocol instead of the concrete MoodleAPI class.
    This decouples business logic from the HTTP implementation and makes unit
    testing trivial — any object with these methods works.
    """

    def get_courses(self) -> list[Course]: ...

    def get_course_participants(self, course_id: CourseId) -> list[Participant]: ...

    def get_grade_report(self, course_id: CourseId) -> GradeReport: ...

    def get_course_assignments(self, course_id: CourseId) -> list[AssignmentMeta]: ...

    def get_assignment_submissions(self, cmid: Cmid) -> list[Submission]: ...

    def get_assignment_brief_files(self, cmid: Cmid) -> list[FileRef]: ...

    def get_assignment_internal_id(self, cmid: Cmid) -> tuple[int, int]: ...

    def get_grade_form_fragment(self, context_id: int, user_id: UserId) -> FormFields: ...

    def submit_grade_for_user(
            self,
            cmid: Cmid,
            user_id: UserId,
            grade: float,
            feedback: str,
            notify_student: bool,
    ) -> float: ...

    def download_file(self, url: str, dest_path: object) -> None: ...

    def send_message(self, user_id: UserId, message: str) -> JSON: ...

    def delete_message(self, message_id: int) -> None: ...

    def get_course_sections(self, course_id: CourseId) -> list[CourseSection]: ...

    def set_module_visible(self, cmid: Cmid, visible: bool) -> None: ...

    def set_section_visible(self, section_id: SectionId, visible: bool) -> None: ...

    def rename_module(self, cmid: Cmid, name: str) -> None: ...

    def rename_section(self, section_id: SectionId, name: str) -> None: ...

    def delete_module(self, cmid: Cmid) -> None: ...

    def move_module(self, course_id: CourseId, cmid: Cmid, target_cmid: int, section_id: SectionId) -> None: ...

    def move_section(self, course_id: CourseId, section_id: SectionId, before_section_id: SectionId) -> None: ...

    def get_module_form(self, cmid: Cmid) -> dict[str, str]: ...

    def update_module(self, cmid: Cmid, changes: dict[str, str]) -> None: ...

    def create_module(
            self,
            course_id: CourseId,
            section_num: int,
            modname: str,
            name: str,
            settings: dict[str, Any] | None = None,
            file_path: str | None = None,
    ) -> Cmid: ...

    def get_course_form(self, course_id: CourseId) -> dict[str, str]: ...

    def update_course(self, course_id: CourseId, changes: dict[str, str]) -> None: ...

from __future__ import annotations

import json
import re
from typing import cast
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag

from moodlectl.client.base import MoodleClientBase
from moodlectl.types import (
    JSON,
    AssignmentMeta,
    Cmid,
    Course,
    CourseId,
    FileRef,
    FormFields,
    GradeReport,
    Participant,
    Submission,
    UserId,
)

# Shown whenever an HTTP response redirects to the login page.
_SESSION_EXPIRED = "Re-login in your browser and update MOODLE_SESSION in .env"


# ── BeautifulSoup attribute helpers ──────────────────────────────────────────
# BS4's type stubs type tag attributes as str | list[str] (_AttributeValue).
# These helpers narrow the result to the concrete types we actually need.

def _attr(tag: Tag, name: str, default: str = "") -> str:
    """Return a tag attribute as a plain string."""
    val = tag.get(name)
    return str(val) if val is not None else default


def _int_attr(tag: Tag, name: str) -> int:
    """Return a tag attribute as an integer (raises ValueError if not numeric)."""
    return int(str(tag[name]))


def _classes(tag: Tag) -> list[str]:
    """Return the tag's class list as a list of strings."""
    val = tag.get("class")
    if isinstance(val, list):
        return [str(c) for c in val]
    return []


class MoodleAPI(MoodleClientBase):

    def _get_soup(self, url: str, params: dict[str, str | int] | None = None, context: str = "") -> BeautifulSoup:
        """GET a Moodle page, check for session expiry, and return a parsed BeautifulSoup.

        Raises RuntimeError with a clear message if the response redirects to login.
        context: short description of what was being loaded (used in the error message).
        """
        resp = self._session.get(url, params=params or {})
        if "login" in resp.url:
            detail = f" while loading {context}" if context else ""
            raise RuntimeError(
                f"Session expired{detail}.\n{_SESSION_EXPIRED}"
            )
        return BeautifulSoup(resp.text, "html.parser")

    # ── Courses ───────────────────────────────────────────────────────────────

    def get_courses(self, classification: str = "all", sort: str = "fullname") -> list[Course]:
        raw = self.ajax("core_course_get_enrolled_courses_by_timeline_classification", {
            "offset": 0,
            "limit": 0,
            "classification": classification,
            "sort": sort,
            "customfieldname": "",
            "customfieldvalue": "",
            "requiredfields": ["id", "fullname", "shortname", "visible", "enddate"],
        })
        data = cast(dict[str, list[Course]], raw)
        return data["courses"]

    # ── Participants ──────────────────────────────────────────────────────────

    def get_course_participants(self, course_id: CourseId) -> list[Participant]:
        """Scrape the participants page for a course.

        Table columns: [checkbox, fullname, email, roles, groups, lastaccess, status]
        """
        soup = self._get_soup(
            f"{self.base_url}/user/index.php",
            params={"id": course_id, "perpage": 5000},
            context=f"participants for course {course_id}",
        )

        table = soup.find("table", {"id": "participants"})
        if not table:
            return []

        tbody = table.find("tbody")
        if not tbody:
            return []

        participants: list[Participant] = []
        for row in tbody.find_all("tr"):
            cols = row.find_all(["td", "th"])
            if len(cols) < 3:
                continue

            # User ID from checkbox input id e.g. id="user1557"
            checkbox = cols[0].find("input")
            user_id: UserId | None = None
            if checkbox:
                cid_attr = _attr(checkbox, "id")
                if cid_attr.startswith("user"):
                    try:
                        user_id = UserId(int(cid_attr.replace("user", "")))
                    except ValueError:
                        pass

            # Fullname: strip the avatar initials (first 2 chars like "AA")
            name_link = cols[1].find("a")
            if name_link:
                fullname = name_link.get_text(strip=True)[2:]
            else:
                fullname = cols[1].get_text(strip=True)

            email = cols[2].get_text(strip=True) if len(cols) > 2 else ""
            roles = cols[3].get_text(strip=True) if len(cols) > 3 else ""
            lastaccess = cols[5].get_text(strip=True) if len(cols) > 5 else ""
            status = cols[6].get_text(strip=True) if len(cols) > 6 else ""

            if not fullname or user_id is None:
                continue

            participants.append({
                "id": user_id,
                "fullname": fullname,
                "email": email,
                "roles": roles,
                "lastaccess": lastaccess,
                "status": status,
            })

        return participants

    # ── Grades ────────────────────────────────────────────────────────────────

    def get_grade_report(self, course_id: CourseId) -> GradeReport:
        """Scrape the grader report (teacher view) for a course, all pages.

        Returns {"columns": [...], "rows": [{"id", "fullname", "email", col: grade, ...}]}
        """
        columns: list[str] = []
        all_student_rows: list[dict[str, str | int]] = []
        page = 0

        while True:
            soup = self._get_soup(
                f"{self.base_url}/grade/report/grader/index.php",
                params={"id": course_id, "page": page},
                context="grade report",
            )

            table = soup.find("table", {"id": "user-grades"})
            if not table:
                break

            all_rows = table.find_all("tr")

            # Parse column headers once (from first page only)
            if not columns:
                heading_row = next(
                    (r for r in all_rows if "heading" in _classes(r)), None
                )
                if heading_row:
                    for th in heading_row.find_all(["th", "td"]):
                        name = None
                        for a in th.find_all("a"):
                            title = _attr(a, "title")
                            if title.startswith("Link to"):
                                name = re.sub(r"^Link to \S+ activity ", "", title).strip()
                                break
                        if not name:
                            raw = th.get_text(separator=" ", strip=True)
                            name = re.sub(
                                r"\s*(Cell actions|Ascending|Descending|Collapse|Expand column)\b.*",
                                "", raw, flags=re.DOTALL,
                            ).strip()
                        columns.append(name or f"col{len(columns)}")

            # Parse student rows on this page
            page_rows = [r for r in all_rows if r.get("data-uid")]
            if not page_rows:
                break

            for tr in page_rows:
                cols = tr.find_all(["td", "th"])
                fullname_raw = cols[0].get_text(strip=True) if cols else ""
                fullname = fullname_raw[2:] if len(fullname_raw) > 2 else fullname_raw
                fullname = re.sub(r"Cell actions.*", "", fullname).strip()
                email = cols[1].get_text(strip=True) if len(cols) > 1 else ""

                grades: dict[str, str] = {}
                grade_cells = [c for c in cols[2:] if "gradecell" in " ".join(_classes(c))]
                for i, cell in enumerate(grade_cells):
                    col_name = columns[i + 2] if i + 2 < len(columns) else f"item_{i}"
                    raw_val = cell.get_text(strip=True)
                    val = re.sub(r"Cell actions.*|Grade analysis.*", "", raw_val).strip()
                    grades[col_name] = val or "-"

                total_col = columns[-1] if columns else "Course total"
                total_cell = next(
                    (c for c in reversed(cols) if "course" in " ".join(_classes(c))), None
                )
                total = re.sub(r"\s+", "", total_cell.get_text(strip=True)) if total_cell else "-"

                row: dict[str, str | int] = {
                    "id": _int_attr(tr, "data-uid"),
                    "fullname": fullname,
                    "email": email,
                    **grades,
                }
                row[total_col] = total
                all_student_rows.append(row)

            # Stop when a page returns fewer than a full page of rows (20)
            if len(page_rows) < 20:
                break
            page += 1

        return {"columns": columns, "rows": all_student_rows}

    # ── Assignments ───────────────────────────────────────────────────────────

    def get_course_assignments(self, course_id: CourseId) -> list[AssignmentMeta]:
        """Scrape the assignment index page for a course.

        Returns list of:
          {cmid, name, due_text, submitted_count}
        """
        soup = self._get_soup(
            f"{self.base_url}/mod/assign/index.php",
            params={"id": course_id},
            context=f"assignments for course {course_id}",
        )

        table = soup.find("table", class_="generaltable")
        if not table:
            return []

        tbody = table.find("tbody")
        if not tbody:
            return []

        assignments: list[AssignmentMeta] = []
        for row in tbody.find_all("tr"):
            cols = row.find_all(["td", "th"])
            if len(cols) < 3:
                continue

            # col 1: assignment name + link containing cmid
            name_cell = cols[1]
            link = name_cell.find("a")
            if not link:
                continue
            name = link.get_text(strip=True)
            href = _attr(link, "href")
            m = re.search(r"[?&]id=(\d+)", href)
            if not m:
                continue
            cmid = Cmid(int(m.group(1)))

            due_text = cols[2].get_text(strip=True) if len(cols) > 2 else ""

            submitted_count = 0
            if len(cols) > 3:
                try:
                    submitted_count = int(cols[3].get_text(strip=True))
                except ValueError:
                    pass

            assignments.append({
                "cmid": cmid,
                "name": name,
                "due_text": due_text,
                "submitted_count": submitted_count,
            })

        return assignments

    def get_assignment_brief_files(self, cmid: Cmid) -> list[FileRef]:
        """Scrape the assignment view page for instructor-attached brief files.

        Returns list of {filename, url} for files attached to the assignment description.
        """
        soup = self._get_soup(
            f"{self.base_url}/mod/assign/view.php",
            params={"id": cmid},
            context=f"assignment {cmid}",
        )

        files: list[FileRef] = []
        for a in soup.find_all("a", href=True):
            href = _attr(a, "href")
            if "pluginfile.php" in href and "mod_assign/introattachment" in href:
                filename = a.get_text(strip=True)
                if filename:
                    files.append({"filename": filename, "url": href})
        return files

    def get_assignment_submissions(self, cmid: Cmid) -> list[Submission]:
        """Scrape the grading page for an assignment.

        Returns list of:
          {user_id, fullname, email, status, grading_status, files: [{filename, url}]}

        Only entries with at least one uploaded file are included.
        """
        soup = self._get_soup(
            f"{self.base_url}/mod/assign/view.php",
            params={"id": cmid, "action": "grading", "perpage": 1000},
            context=f"submissions for assignment {cmid}",
        )

        table = soup.find("table", class_="generaltable")
        if not table:
            return []

        tbody = table.find("tbody")
        if not tbody:
            return []

        results: list[Submission] = []
        for row in tbody.find_all("tr"):
            cols = row.find_all(["td", "th"])
            if len(cols) < 9:
                continue

            # col 2: fullname + link with user_id
            name_cell = cols[2]
            fullname = name_cell.get_text(strip=True)
            user_id: UserId | None = None
            profile_link = name_cell.find("a")
            if profile_link:
                m = re.search(r"[?&]id=(\d+)", _attr(profile_link, "href"))
                if m:
                    user_id = UserId(int(m.group(1)))

            if not fullname or user_id is None:
                continue

            email = cols[3].get_text(strip=True)
            status_text = cols[4].get_text(strip=True)
            grading_status = cols[5].get_text(strip=True) if len(cols) > 5 else ""

            # col 8: file submissions
            files: list[FileRef] = []
            for a in cols[8].find_all("a"):
                href = _attr(a, "href")
                if "pluginfile.php" in href:
                    files.append({"filename": a.get_text(strip=True), "url": href})

            if not files:
                continue

            results.append({
                "user_id": user_id,
                "fullname": fullname,
                "email": email,
                "status": status_text,
                "grading_status": grading_status,
                "files": files,
            })

        return results

    def get_assignment_internal_id(self, cmid: Cmid) -> tuple[int, int]:
        """Return (internal_assignment_id, context_id) for a given cmid.

        These IDs are needed for grade submission and differ from the cmid.
        Scraped from the grader page's data attributes.
        """
        soup = self._get_soup(
            f"{self.base_url}/mod/assign/view.php",
            params={"id": cmid, "action": "grader"},
            context=f"grader page for assignment {cmid}",
        )

        grade_div = soup.find(attrs={"data-region": "grade"})
        if not grade_div:
            raise RuntimeError(f"Could not find grade panel for cmid={cmid}")
        assignment_id = _int_attr(grade_div, "data-assignmentid")
        context_id = _int_attr(grade_div, "data-contextid")
        return assignment_id, context_id

    def get_grade_form_fragment(self, context_id: int, user_id: UserId) -> FormFields:
        """Load the grading form fragment for a student.

        Returns the raw form field dict (as parsed from the fragment HTML).
        The itemid for the feedback editor changes per request — always fetch
        a fresh fragment immediately before submitting.
        """
        raw = self.ajax("core_get_fragment", {
            "component": "mod_assign",
            "callback": "gradingpanel",
            "contextid": context_id,
            "args": [
                {"name": "userid", "value": str(user_id)},
                {"name": "attemptnumber", "value": "-1"},
                {"name": "jsonformdata", "value": ""},
            ],
        })
        result = cast(dict[str, str], raw)
        html = result.get("html", "")
        soup = BeautifulSoup(html, "html.parser")

        fields: FormFields = {}
        for el in soup.find_all(["input", "textarea", "select"]):
            name = _attr(el, "name")
            if not name:
                continue
            if el.name == "textarea":
                fields[name] = el.get_text()
            elif el.name == "select":
                selected = el.find("option", selected=True)
                fields[name] = _attr(selected, "value") if selected else ""
            else:
                fields[name] = _attr(el, "value")

        # Parse grade max from label text e.g. "Grade out of 10"
        label = soup.find("label", {"for": "id_grade"})
        grade_max: str = ""
        if label:
            m = re.search(r"out of\s+([\d.]+)", label.get_text(), re.IGNORECASE)
            if m:
                grade_max = m.group(1)

        fields["__grade_max__"] = grade_max
        return fields

    def submit_grade_for_user(
            self,
            cmid: Cmid,
            user_id: UserId,
            grade: float,
            feedback: str = "",
            notify_student: bool = False,
    ) -> float:
        """High-level grade submission: resolves IDs, fetches fresh form, submits.

        Returns the grade_max so the caller can display it.
        Raises RuntimeError if the grade could not be saved.

        Steps:
          1. Scrape grader page → (assignment_id, context_id) — different from cmid
          2. Fetch fresh form fragment — itemid changes each request, must not be cached
          3. Submit via mod_assign_submit_grading_form — empty list = success
        """
        # 1. Resolve internal IDs from cmid
        assignment_id, context_id = self.get_assignment_internal_id(cmid)

        # 2. Load fresh form fragment (itemid is one-time use)
        fields = self.get_grade_form_fragment(context_id, user_id)
        grade_max = float(fields.pop("__grade_max__") or 0)

        # 3. Override grade, feedback, and notification preference
        fields["grade"] = str(grade)
        fields["assignfeedbackcomments_editor[text]"] = feedback
        fields["sendstudentnotifications"] = "1" if notify_student else "0"

        # 4. Submit
        raw = self.ajax("mod_assign_submit_grading_form", {
            "assignmentid": assignment_id,
            "userid": user_id,
            "jsonformdata": json.dumps(urlencode(fields)),
        })
        result = cast(list[dict[str, str]], raw)

        # Empty list = success; non-empty list = validation errors
        if result:
            errors = "; ".join(e.get("message", str(e)) for e in result)
            raise RuntimeError(f"Grade submission failed: {errors}")

        return grade_max

    def download_file(self, url: str, dest_path: object) -> None:
        """Download an authenticated Moodle file (pluginfile.php) to dest_path.

        Rewrites webservice/pluginfile.php → pluginfile.php for session-cookie auth.
        """
        from pathlib import Path

        # Moodle AJAX sometimes returns webservice/pluginfile.php URLs even when
        # using session auth — rewrite to the regular pluginfile.php path.
        url = url.replace("/webservice/pluginfile.php", "/pluginfile.php")

        path = Path(str(dest_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        resp = self._session.get(url, stream=True)
        resp.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)

    # ── Messages ──────────────────────────────────────────────────────────────

    def send_message(self, user_id: UserId, message: str) -> JSON:
        return self.ajax("core_message_send_instant_messages", {
            "messages": [{"touserid": user_id, "text": message, "textformat": 1}],
        })

    def delete_message(self, message_id: int) -> None:
        self.ajax("core_message_delete_message", {"messageid": message_id})

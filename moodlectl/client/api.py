from __future__ import annotations

from moodlectl.client.base import MoodleClientBase


class MoodleAPI(MoodleClientBase):

    # ── Courses ───────────────────────────────────────────────────────────────

    def get_courses(self, classification: str = "all", sort: str = "fullname") -> list[dict]:
        data = self.ajax("core_course_get_enrolled_courses_by_timeline_classification", {
            "offset": 0,
            "limit": 0,
            "classification": classification,
            "sort": sort,
            "customfieldname": "",
            "customfieldvalue": "",
            "requiredfields": ["id", "fullname", "shortname", "visible", "enddate"],
        })
        return data["courses"]

    # ── Participants ──────────────────────────────────────────────────────────

    def get_course_participants(self, course_id: int) -> list[dict]:
        return self.ajax("core_enrol_get_enrolled_users", {
            "courseid": course_id,
            "options": [
                {"name": "onlyactive", "value": 1},
                {"name": "userfields", "value": "id,fullname,email,lastaccess,roles"},
            ],
        })

    # ── Grades ────────────────────────────────────────────────────────────────

    def get_grades(self, course_id: int, user_id: int = 0) -> dict:
        return self.ajax("gradereport_user_get_grade_items", {
            "courseid": course_id,
            "userid": user_id,
        })

    # ── Assignments ───────────────────────────────────────────────────────────

    def get_assignments(self, course_ids: list[int]) -> dict:
        return self.ajax("mod_assign_get_assignments", {
            "courseids": course_ids,
        })

    # ── Messages ──────────────────────────────────────────────────────────────

    def send_message(self, user_id: int, message: str) -> dict:
        return self.ajax("core_message_send_instant_messages", {
            "messages": [{"touserid": user_id, "text": message, "textformat": 1}],
        })

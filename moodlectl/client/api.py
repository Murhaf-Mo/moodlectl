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
        """Scrape the participants page for a course.

        Table columns: [checkbox, fullname, email, roles, groups, lastaccess, status]
        """
        from bs4 import BeautifulSoup

        resp = self._session.get(
            f"{self.base_url}/user/index.php",
            params={"id": course_id, "perpage": 5000},
        )

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", {"id": "participants"})

        if not table:
            return []

        participants = []
        for row in table.find("tbody").find_all("tr"):
            cols = row.find_all(["td", "th"])
            if len(cols) < 3:
                continue

            # User ID from checkbox input id e.g. id="user1557"
            checkbox = cols[0].find("input")
            user_id = 0
            if checkbox and checkbox.get("id", "").startswith("user"):
                try:
                    user_id = int(checkbox["id"].replace("user", ""))
                except ValueError:
                    pass

            # Fullname: strip the avatar initials (first 2 chars like "AA")
            name_link = cols[1].find("a")
            fullname = name_link.get_text(strip=True)[2:] if name_link else cols[1].get_text(strip=True)

            email = cols[2].get_text(strip=True) if len(cols) > 2 else ""
            roles = cols[3].get_text(strip=True) if len(cols) > 3 else ""
            lastaccess = cols[5].get_text(strip=True) if len(cols) > 5 else ""
            status = cols[6].get_text(strip=True) if len(cols) > 6 else ""

            if not fullname or user_id == 0:
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

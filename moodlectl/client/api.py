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

    def get_grade_report(self, course_id: int) -> dict:
        """Scrape the grader report (teacher view) for a course, all pages.

        Returns {"columns": [...], "rows": [{"id", "fullname", "email", col: grade, ...}]}
        """
        import re
        from bs4 import BeautifulSoup

        columns: list[str] = []
        all_student_rows: list = []
        page = 0

        while True:
            resp = self._session.get(
                f"{self.base_url}/grade/report/grader/index.php",
                params={"id": course_id, "page": page},
            )

            if "login" in resp.url:
                raise RuntimeError(
                    "Grade report requires a fresh session.\n"
                    "Re-login in your browser and update MOODLE_SESSION in .env"
                )

            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.find("table", {"id": "user-grades"})
            if not table:
                break

            all_rows = table.find_all("tr")

            # Parse column headers once (from first page)
            if not columns:
                heading_row = next(
                    (r for r in all_rows if "heading" in r.get("class", [])), None
                )
                if heading_row:
                    for th in heading_row.find_all(["th", "td"]):
                        name = None
                        for a in th.find_all("a"):
                            title = a.get("title", "")
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
                grade_cells = [c for c in cols[2:] if "gradecell" in " ".join(c.get("class", []))]
                for i, cell in enumerate(grade_cells):
                    col_name = columns[i + 2] if i + 2 < len(columns) else f"item_{i}"
                    raw_val = cell.get_text(strip=True)
                    val = re.sub(r"Cell actions.*|Grade analysis.*", "", raw_val).strip()
                    grades[col_name] = val or "-"

                total_col = columns[-1] if columns else "Course total"
                total_cell = next(
                    (c for c in reversed(cols) if "course" in " ".join(c.get("class", []))), None
                )
                total = re.sub(r"\s+", "", total_cell.get_text(strip=True)) if total_cell else "-"

                row = {"id": int(tr["data-uid"]), "fullname": fullname, "email": email, **grades}
                row[total_col] = total
                all_student_rows.append(row)

            # Stop when the page returned fewer rows than a full page (20)
            if len(page_rows) < 20:
                break
            page += 1

        return {"columns": columns, "rows": all_student_rows}

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

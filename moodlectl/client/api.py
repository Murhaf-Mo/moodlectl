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

    def get_course_assignments(self, course_id: int) -> list[dict]:
        """Scrape the assignment index page for a course.

        Returns list of:
          {cmid, name, due_text, submitted_count}
        """
        import re
        from bs4 import BeautifulSoup

        resp = self._session.get(
            f"{self.base_url}/mod/assign/index.php",
            params={"id": course_id},
        )
        if "login" in resp.url:
            raise RuntimeError(
                "Session expired while loading assignments.\n"
                "Re-login in your browser and update MOODLE_SESSION in .env"
            )

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="generaltable")
        if not table:
            return []

        tbody = table.find("tbody")
        if not tbody:
            return []

        assignments = []
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
            href = link.get("href", "")
            m = re.search(r"[?&]id=(\d+)", href)
            if not m:
                continue
            cmid = int(m.group(1))

            # col 2: due date text
            due_text = cols[2].get_text(strip=True) if len(cols) > 2 else ""

            # col 3: number of submitted assignments
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

    def get_assignment_brief_files(self, cmid: int) -> list[dict]:
        """Scrape the assignment view page for instructor-attached brief files.

        Returns list of {filename, url} for files attached to the assignment description.
        """
        from bs4 import BeautifulSoup

        resp = self._session.get(
            f"{self.base_url}/mod/assign/view.php",
            params={"id": cmid},
        )
        if "login" in resp.url:
            raise RuntimeError(
                "Session expired while loading assignment.\n"
                "Re-login in your browser and update MOODLE_SESSION in .env"
            )

        soup = BeautifulSoup(resp.text, "html.parser")
        files = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "pluginfile.php" in href and "mod_assign/introattachment" in href:
                filename = a.get_text(strip=True)
                if filename:
                    files.append({"filename": filename, "url": href})
        return files

    def get_assignment_submissions(self, cmid: int) -> list[dict]:
        """Scrape the grading page for an assignment.

        Returns list of:
          {user_id, fullname, email, status, files: [{filename, url}]}

        Only entries with at least one file are included.
        """
        import re
        from bs4 import BeautifulSoup

        resp = self._session.get(
            f"{self.base_url}/mod/assign/view.php",
            params={"id": cmid, "action": "grading", "perpage": 1000},
        )
        if "login" in resp.url:
            raise RuntimeError(
                "Session expired while loading submissions.\n"
                "Re-login in your browser and update MOODLE_SESSION in .env"
            )

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="generaltable")
        if not table:
            return []

        tbody = table.find("tbody")
        if not tbody:
            return []

        results = []
        for row in tbody.find_all("tr"):
            cols = row.find_all(["td", "th"])
            if len(cols) < 9:
                continue

            # col 2 (c2): fullname + link with user_id
            name_cell = cols[2]
            fullname = name_cell.get_text(strip=True)
            user_id = 0
            profile_link = name_cell.find("a")
            if profile_link:
                m = re.search(r"[?&]id=(\d+)", profile_link.get("href", ""))
                if m:
                    user_id = int(m.group(1))

            if not fullname or user_id == 0:
                continue

            # col 3 (c3 email): email
            email = cols[3].get_text(strip=True)

            # col 4 (c4): submission status
            status_text = cols[4].get_text(strip=True)

            # col 8 (c8): file submissions
            file_cell = cols[8]
            files = []
            for a in file_cell.find_all("a"):
                href = a.get("href", "")
                if "pluginfile.php" in href:
                    files.append({
                        "filename": a.get_text(strip=True),
                        "url": href,
                    })

            if not files:
                continue

            results.append({
                "user_id": user_id,
                "fullname": fullname,
                "email": email,
                "status": status_text,
                "files": files,
            })

        return results

    def download_file(self, url: str, dest_path) -> None:
        """Download an authenticated Moodle file (pluginfile.php) to dest_path."""
        from pathlib import Path

        # Moodle AJAX sometimes returns webservice/pluginfile.php URLs even when
        # using session auth — rewrite to the regular pluginfile.php path.
        url = url.replace("/webservice/pluginfile.php", "/pluginfile.php")

        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        resp = self._session.get(url, stream=True)
        resp.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)

    # ── Messages ──────────────────────────────────────────────────────────────

    def send_message(self, user_id: int, message: str) -> dict:
        return self.ajax("core_message_send_instant_messages", {
            "messages": [{"touserid": user_id, "text": message, "textformat": 1}],
        })

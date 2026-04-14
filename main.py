import re
import requests

BASE_URL = "https://mylms.cck.edu.kw"

# ── Auth: paste these from your browser after logging in via Microsoft ────────
# F12 → Application → Cookies → MoodleSession value
MOODLE_SESSION_COOKIE = "8as9pvmv193702hbjr9riij2u1"
# F12 → Network → any request to service.php → look in request body for sesskey
SESSKEY = "Uxaqk9y617"
# ─────────────────────────────────────────────────────────────────────────────


class MoodleClient:
    def __init__(self, base_url, moodle_session, sesskey):
        self.base_url = base_url
        self.sesskey = sesskey
        self.session = requests.Session()
        self.session.cookies.set("MoodleSession", moodle_session)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": f"{base_url}/my/",
            "Origin": base_url,
            "Content-Type": "application/json",
        })
        print(f"MoodleClient ready. Sesskey: {self.sesskey}")

    def refresh_sesskey(self):
        """Call this if you get 'sesskey' errors — grabs a fresh one from the dashboard."""
        resp = self.session.get(f"{self.base_url}/my/")
        match = re.search(r'"sesskey":"([^"]+)"', resp.text)
        if match:
            self.sesskey = match.group(1)
            print(f"Sesskey refreshed: {self.sesskey}")
        else:
            raise Exception("Could not refresh sesskey — session may have expired, re-paste your MoodleSession cookie")

    def ajax(self, methodname, args):
        resp = self.session.post(
            f"{self.base_url}/lib/ajax/service.php",
            params={"sesskey": self.sesskey, "info": methodname},
            json=[{"index": 0, "methodname": methodname, "args": args}]
        )
        if not resp.text.strip():
            raise Exception("Empty response — MoodleSession cookie has expired. Re-login in browser and paste a fresh MoodleSession value.")
        result = resp.json()
        if result[0].get("error"):
            raise Exception(result[0]["exception"]["message"])
        return result[0]["data"]

    # ── Courses ──────────────────────────────────────────────────────────────

    def get_courses(self, classification="all", sort="fullname"):
        data = self.ajax("core_course_get_enrolled_courses_by_timeline_classification", {
            "offset": 0,
            "limit": 0,
            "classification": classification,
            "sort": sort,
            "customfieldname": "",
            "customfieldvalue": "",
            "requiredfields": ["id", "fullname", "shortname", "visible", "enddate"]
        })
        return data["courses"]

    # ── Users ─────────────────────────────────────────────────────────────────

    def get_enrolled_users(self, course_id):
        return self.ajax("core_enrol_get_enrolled_users", {"courseid": course_id})

    # ── Grades ────────────────────────────────────────────────────────────────

    def get_grades(self, course_id, user_id=0):
        return self.ajax("gradereport_user_get_grade_items", {
            "courseid": course_id,
            "userid": user_id,
        })

    # ── Assignments ───────────────────────────────────────────────────────────

    def get_assignments(self, course_ids: list):
        return self.ajax("mod_assign_get_assignments", {
            "courseids": course_ids,
        })

    # ── Messages ──────────────────────────────────────────────────────────────

    def send_message(self, user_id, message):
        return self.ajax("core_message_send_instant_messages", {
            "messages": [{"touserid": user_id, "text": message, "textformat": 1}]
        })


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    client = MoodleClient(BASE_URL, MOODLE_SESSION_COOKIE, SESSKEY)

    # List all your courses
    courses = client.get_courses()
    print(f"\nYou are enrolled in {len(courses)} course(s):\n")
    for c in courses:
        print(f"  [{c['id']}] {c['fullname']}  ({c['shortname']})")
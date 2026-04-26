"""End-to-end smoke tests against the live https://school.moodledemo.net demo.

These run real HTTP requests, create real Moodle artefacts, and clean them up
afterwards. They are gated by the `demo` pytest marker so a regular `pytest`
run skips them.

Run them with::

    pytest -m demo                    # whole suite (~60 seconds)
    pytest -m demo -k content         # one group
    pytest -m demo -x -vv             # stop at first failure, verbose

Pre-requisites:
    1. `moodlectl auth set-url https://school.moodledemo.net`
    2. `moodlectl auth login` (signed in as `teacher`/`moodle`)
    3. `MOODLE_BASE_URL=https://school.moodledemo.net` in your .env

The suite refuses to run if MOODLE_BASE_URL points anywhere else, so you can
never accidentally exercise it against your real institution Moodle.

Course IDs used (these are stable on the demo):
    - 83  Sandbox (write-side tests; we own this one)
    - 51  Moodle Mountain (rich participant data)
    - 69  Mindful Course Creation (rich grades + analytics data)
    - 978 cmid: 'Check your understanding' quiz with real attempts
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.demo

# ── Constants ────────────────────────────────────────────────────────────────-

DEMO_HOST = "school.moodledemo.net"
SANDBOX_COURSE = 83
PARTICIPANTS_COURSE = 51
GRADES_COURSE = 69
QUIZ_WITH_ATTEMPTS = 978  # cmid

CLI = [sys.executable, "-m", "moodlectl"]


# ── Guards ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _guard_demo_url() -> None:  # pyright: ignore[reportUnusedFunction]
    """Refuse to run unless MOODLE_BASE_URL points at the public demo AND the
    session is currently valid. Scope=session means we check once and abort
    the whole suite up-front, not surface a wave of cascading failures.
    """
    base = os.environ.get("MOODLE_BASE_URL", "")
    if DEMO_HOST not in base:
        env_file = Path(".env")
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("MOODLE_BASE_URL"):
                    base = line.split("=", 1)[1].strip().strip("'\"")
                    break
    if DEMO_HOST not in base:
        pytest.exit(
            f"Demo suite refuses to run: MOODLE_BASE_URL={base!r} is not "
            f"https://{DEMO_HOST}. Run `moodlectl auth set-url "
            f"https://{DEMO_HOST}` first.",
            returncode=2,
        )

    # Verify session is alive before we burn 2+ minutes on doomed tests.
    proc = subprocess.run(
        [*CLI, "auth", "check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30,
    )
    if proc.returncode != 0 or "Session valid" not in proc.stdout:
        pytest.exit(
            f"Demo suite refuses to run: session is invalid or expired.\n"
            f"Run `moodlectl auth login` to refresh, then re-run pytest.\n"
            f"--- auth check output ---\n{proc.stdout}{proc.stderr}",
            returncode=2,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(*args: str, expect_ok: bool = True, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI; return CompletedProcess with combined stdout+stderr."""
    proc = subprocess.run(
        [*CLI, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if expect_ok and proc.returncode != 0:
        msg = (
            f"\n--- CLI exit {proc.returncode} for: moodlectl {' '.join(args)}\n"
            f"--- stdout ---\n{proc.stdout}\n"
            f"--- stderr ---\n{proc.stderr}"
        )
        pytest.fail(msg)
    return proc


def assert_contains(text: str, *needles: str) -> None:
    for needle in needles:
        assert needle in text, f"expected {needle!r} in output, got:\n{text}"


def assert_not_in(text: str, *needles: str) -> None:
    for needle in needles:
        assert needle not in text, f"unexpected {needle!r} in output:\n{text}"


# ── auth ──────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_check_session_valid(self) -> None:
        out = run("auth", "check").stdout
        assert_contains(out, "Session valid")

    # set-url / login / logout / set-session intentionally not tested:
    #   they rewrite .env and could lock the rest of the suite out.


# ── courses ───────────────────────────────────────────────────────────────────

class TestCourses:
    def test_list(self) -> None:
        out = run("courses", "list").stdout
        # Sandbox is the canonical write-target; presence proves auth + parsing.
        assert "Sandbox" in out, out

    def test_list_csv(self) -> None:
        out = run("courses", "list", "--output", "csv").stdout
        assert_contains(out, "id,fullname,shortname")

    def test_participants_one_course(self) -> None:
        out = run("courses", "participants", "--course", str(PARTICIPANTS_COURSE)).stdout
        # The table is truncated for narrow terminals; just check it produced
        # at least the column headers + a row of data.
        assert_contains(out, "fullname", "email")
        assert out.count("\n") > 5, f"participants output looks empty:\n{out}"

    def test_participants_role_filter(self) -> None:
        # Just check the command succeeds — role filtering may match nobody on
        # a given demo seed, which is not a failure.
        run("courses", "participants", "--course", str(PARTICIPANTS_COURSE),
            "--role", "teacher")

    def test_inactive(self) -> None:
        # may or may not have results; just check the command exits cleanly
        run("courses", "inactive", "--course", str(PARTICIPANTS_COURSE), "--days", "1")


# ── grades ────────────────────────────────────────────────────────────────────

class TestGrades:
    def test_show_one_course(self) -> None:
        out = run("grades", "show", "--course", str(GRADES_COURSE)).stdout
        # Course-total grades report; just ensure it produced a table with
        # the expected column headers, not a literal email format.
        assert "fullname" in out.lower() or "course total" in out.lower(), out

    def test_show_full(self) -> None:
        run("grades", "show", "--course", str(GRADES_COURSE), "--full")

    def test_stats(self) -> None:
        out = run("grades", "stats", "--course", str(GRADES_COURSE)).stdout
        # Stats output mentions mean/median or no-data message
        assert "mean" in out.lower() or "no" in out.lower() or "median" in out.lower()


# ── assignments (read-only) ───────────────────────────────────────────────────

class TestAssignmentsRead:
    def test_list(self) -> None:
        run("assignments", "list")

    def test_list_active(self) -> None:
        run("assignments", "list", "--status", "active")

    def test_due_soon_wide(self) -> None:
        run("assignments", "due-soon", "--days", "365")

    def test_ungraded(self) -> None:
        run("assignments", "ungraded")

    def test_missing(self) -> None:
        run("assignments", "missing")


# ── analytics ─────────────────────────────────────────────────────────────────

class TestAnalytics:
    def test_grades_dist(self) -> None:
        run("analytics", "grades-dist", "--course", str(GRADES_COURSE))

    def test_letter_grades(self) -> None:
        run("analytics", "letter-grades", "--course", str(GRADES_COURSE))

    def test_submission_status(self) -> None:
        run("analytics", "submission-status", "--course", str(GRADES_COURSE))

    def test_at_risk(self) -> None:
        run("analytics", "at-risk", "--course", str(GRADES_COURSE), "--threshold", "100")

    def test_summary_save(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "reports"
        run("analytics", "summary", "--course", str(GRADES_COURSE), "--save-dir", str(out_dir))
        assert any(out_dir.glob("*.png")), f"no PNGs written to {out_dir}"


# ── content (read-only) ───────────────────────────────────────────────────────

class TestContentRead:
    def test_list_sandbox(self) -> None:
        out = run("content", "list", "--course", str(SANDBOX_COURSE)).stdout
        assert_contains(out, "Sandbox")

    def test_list_filter_by_type(self) -> None:
        run("content", "list", "--course", str(PARTICIPANTS_COURSE), "--type", "forum")


# ── content (write — self-cleaning) ───────────────────────────────────────────

class TestContentWrite:
    def test_label_lifecycle(self) -> None:
        """create label → list → rename → hide → unhide → delete."""
        # Create
        out = run(
            "content", "create",
            "--course", str(SANDBOX_COURSE), "--section", "1",
            "--type", "label",
            "--set", "content=<p>e2e label</p>",
        ).stdout
        # Find the new cmid in subsequent listing
        list_out = run("content", "list", "--course", str(SANDBOX_COURSE)).stdout
        cmids = _find_cmids_for_label(list_out, "e2e label")
        assert cmids, f"label not found after create; output:\n{list_out}\ncreate output:\n{out}"
        cmid = cmids[-1]

        try:
            # Rename
            run("content", "rename",
                "--course", str(SANDBOX_COURSE), "--cmid", str(cmid),
                "--name", "e2e label renamed")
            # Hide
            run("content", "hide", "--course", str(SANDBOX_COURSE), "--cmid", str(cmid))
            # Unhide
            run("content", "unhide", "--course", str(SANDBOX_COURSE), "--cmid", str(cmid))
        finally:
            run("content", "delete", "--course", str(SANDBOX_COURSE),
                "--cmid", str(cmid), "--force")


def _find_cmids_for_label(content_list_output: str, needle: str) -> list[int]:
    """Parse `content list` output for cmids of modules whose name contains `needle`."""
    import re
    out: list[int] = []
    for line in content_list_output.splitlines():
        if needle.lower() in line.lower():
            m = re.search(r"cmid=(\d+)", line)
            if m:
                out.append(int(m.group(1)))
    return out


# ── assignments (write — self-cleaning) ───────────────────────────────────────

class TestAssignmentsWrite:
    def test_create_and_delete(self) -> None:
        # Create a hidden assignment
        proc = run(
            "assignments", "create",
            "--course", str(SANDBOX_COURSE), "--section", "1",
            "--name", "e2e assignment",
            "--description", "End-to-end smoke test.",
            "--due", "2026-12-31T23:59",
            "--max-grade", "10",
            "--filetypes", ".pdf",
            "--hidden",
        )
        out = proc.stdout
        assert_contains(out, "Created assignment")
        # Extract cmid
        import re
        m = re.search(r"cmid=(\d+)", out)
        assert m, f"no cmid in output: {out}"
        cmid = int(m.group(1))

        try:
            list_out = run("assignments", "list", "--course", str(SANDBOX_COURSE)).stdout
            assert "e2e assignment" in list_out
        finally:
            run("assignments", "delete",
                "--assignment", str(cmid), "--course", str(SANDBOX_COURSE), "--yes")


# ── quizzes (read-only) ───────────────────────────────────────────────────────

class TestQuizzesRead:
    def test_list(self) -> None:
        run("quizzes", "list")

    def test_attempts(self) -> None:
        # cmid 978 typically has 2 graded attempts on the demo, but the demo
        # state can drift. Accept either real rows or the empty-result message.
        out = run("quizzes", "attempts", "--quiz", str(QUIZ_WITH_ATTEMPTS)).stdout
        assert ("Finished" in out
                or "No attempts found" in out
                or "fullname" in out.lower()), out

    def test_results(self) -> None:
        out = run("quizzes", "results", "--quiz", str(QUIZ_WITH_ATTEMPTS)).stdout
        assert ("Best Grade" in out
                or "No graded attempts" in out
                or "fullname" in out.lower()), out

    def test_info(self) -> None:
        out = run("quizzes", "info", "--quiz", str(QUIZ_WITH_ATTEMPTS)).stdout
        assert ("total_attempts" in out
                or "no attempts" in out.lower()), out


# ── quizzes (write — self-cleaning) ───────────────────────────────────────────

class TestQuizzesWrite:
    def test_quiz_delete_lifecycle(self) -> None:
        """Create a bare quiz via the python API and delete it via CLI."""
        # Use the in-process helper to create a throwaway quiz cheaply
        from moodlectl.client import MoodleClient
        from moodlectl.config import Config
        from moodlectl.types import CourseId
        client = MoodleClient.from_config(Config.load())
        cmid = client.create_module(
            CourseId(SANDBOX_COURSE), 1, "quiz", "e2e quiz", settings=None,
        )
        try:
            list_out = run("quizzes", "list", "--course", str(SANDBOX_COURSE)).stdout
            assert "e2e quiz" in list_out
        finally:
            run("quizzes", "delete",
                "--quiz", str(cmid), "--course", str(SANDBOX_COURSE), "--yes")


# ── questions (read-only) ─────────────────────────────────────────────────────

class TestQuestionsRead:
    def test_list_categories(self) -> None:
        run("questions", "list-categories", "--course", str(PARTICIPANTS_COURSE))


# ── announcements (read-only) ─────────────────────────────────────────────────

class TestAnnouncementsRead:
    def test_list(self) -> None:
        # Sandbox forum cmid=1612 was visible from the earlier session work.
        # We use the course-level form to avoid needing a hardcoded cmid here.
        run("announcements", "list", "--course", str(SANDBOX_COURSE), "--limit", "5")


# ── summary ───────────────────────────────────────────────────────────────────

class TestSummary:
    def test_summary(self) -> None:
        out = run("summary").stdout
        assert_contains(out, "Enrolled courses")

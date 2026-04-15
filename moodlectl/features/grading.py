from __future__ import annotations

from moodlectl.client import MoodleClient


def submit_grade(
    client: MoodleClient,
    cmid: int,
    user_id: int,
    grade: float,
    feedback: str = "",
    notify_student: bool = False,
) -> dict:
    """Submit a grade for one student on one assignment.

    Returns: {user_id, grade, grade_max, grade_pct, feedback}
    Raises RuntimeError on failure (e.g. grade out of range, session expired).
    """
    grade_max = client.submit_grade_for_user(
        cmid=cmid,
        user_id=user_id,
        grade=grade,
        feedback=feedback,
        notify_student=notify_student,
    )
    grade_pct = round(grade / grade_max * 100, 1) if grade_max else None
    return {
        "user_id": user_id,
        "grade": grade,
        "grade_max": grade_max,
        "grade_pct": grade_pct,
        "feedback": feedback,
    }


def batch_grade(
    client: MoodleClient,
    cmid: int,
    rows: list[dict],
    dry_run: bool = False,
) -> list[dict]:
    """Submit grades from a list of row dicts, each with user_id, grade, feedback.

    dry_run=True logs what would be submitted without writing anything to Moodle.
    Notifications are always off for batch submissions.

    Returns list of result dicts:
      {user_id, grade, grade_max, grade_pct, ok, error}
    where ok=True means success, ok=False means error (see 'error' field),
    and ok='(dry run)' means the row was validated but not submitted.
    """
    results = []

    for row in rows:
        user_id = int(row["user_id"])
        grade = float(row["grade"])
        feedback = str(row.get("feedback", ""))
        feedback_preview = feedback[:40] + ("…" if len(feedback) > 40 else "")

        if dry_run:
            results.append({
                "user_id": user_id,
                "grade": grade,
                "feedback": feedback_preview,
                "ok": "(dry run)",
                "error": "",
            })
            continue

        try:
            grade_max = client.submit_grade_for_user(
                cmid=cmid,
                user_id=user_id,
                grade=grade,
                feedback=feedback,
                notify_student=False,
            )
            grade_pct = round(grade / grade_max * 100, 1) if grade_max else None
            results.append({
                "user_id": user_id,
                "grade": grade,
                "grade_max": grade_max,
                "grade_pct": grade_pct,
                "ok": True,
                "error": "",
            })
        except Exception as exc:
            results.append({
                "user_id": user_id,
                "grade": grade,
                "grade_max": "?",
                "grade_pct": None,
                "ok": False,
                "error": str(exc),
            })

    return results

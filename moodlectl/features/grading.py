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

    Returns a result dict: {user_id, grade, grade_max, grade_pct, feedback}
    Raises RuntimeError on failure.
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

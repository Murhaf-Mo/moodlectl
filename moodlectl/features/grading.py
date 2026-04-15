from __future__ import annotations

from moodlectl.types import BatchResult, Cmid, GradeResult, MoodleClientProtocol, UserId


def submit_grade(
    client: MoodleClientProtocol,
    cmid: Cmid,
    user_id: UserId,
    grade: float,
    feedback: str = "",
    notify_student: bool = False,
) -> GradeResult:
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
    client: MoodleClientProtocol,
    cmid: Cmid,
    rows: list[dict[str, str | None]],
    dry_run: bool = False,
) -> list[BatchResult]:
    """Submit grades from a list of row dicts, each with user_id, grade, feedback.

    dry_run=True logs what would be submitted without writing anything to Moodle.
    Notifications are always off for batch submissions.

    Returns list of result dicts:
      {user_id, grade, grade_max, grade_pct, ok, error}
    where ok=True means success, ok=False means error (see 'error' field),
    and ok='(dry run)' means the row was validated but not submitted.
    """
    results: list[BatchResult] = []

    for row in rows:
        user_id = UserId(int(row["user_id"] or 0))
        grade = float(row["grade"] or 0)
        feedback = str(row.get("feedback") or "")

        if dry_run:
            preview = feedback[:40] + ("…" if len(feedback) > 40 else "")
            results.append({
                "user_id": user_id,
                "grade": grade,
                "grade_max": "",
                "grade_pct": None,
                "ok": "(dry run)",
                "error": preview,
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

from __future__ import annotations

from moodlectl.types import (
    Cmid,
    CourseId,
    MoodleClientProtocol,
    QuizAttempt,
    QuizListing,
    QuizResult,
    UserId,
)


def list_quizzes(
        client: MoodleClientProtocol,
        course_ids: list[CourseId],
) -> list[QuizListing]:
    """Walk course sections and return every quiz module across the given courses."""
    out: list[QuizListing] = []
    for cid in course_ids:
        try:
            sections = client.get_course_sections(cid)
        except Exception:
            continue
        for section in sections:
            for mod in section["modules"]:
                if mod["modname"] != "quiz":
                    continue
                out.append({
                    "course_id": cid,
                    "cmid": mod["cmid"],
                    "name": mod["name"],
                    "visible": int(mod.get("visible", 1)),
                })
    return out


def _to_attempt(cmid: Cmid, raw: dict[str, str]) -> QuizAttempt:
    uid = raw.get("user_id") or ""
    return {
        "cmid": cmid,
        "attempt_id": int(raw.get("attempt_id") or 0),
        "user_id": UserId(int(uid)) if uid.isdigit() else None,
        "fullname": raw.get("fullname", ""),
        "email": raw.get("email", ""),
        "state": raw.get("state", ""),
        "started": raw.get("started", ""),
        "completed": raw.get("completed", ""),
        "duration": raw.get("duration", ""),
        "grade": raw.get("grade", ""),
        "max_grade": raw.get("max_grade", ""),
    }


def get_attempts(
        client: MoodleClientProtocol,
        cmid: Cmid,
) -> list[QuizAttempt]:
    """List every attempt for one quiz."""
    raw = client.get_quiz_attempts(cmid)
    return [_to_attempt(cmid, r) for r in raw]


def _grade_value(g: str) -> float | None:
    """Parse a Moodle grade cell into a float for max() comparison."""
    g = g.strip()
    if not g or g == "-" or g.lower() == "not yet graded":
        return None
    try:
        return float(g.replace(",", "."))
    except ValueError:
        return None


def get_results(
        client: MoodleClientProtocol,
        cmid: Cmid,
) -> list[QuizResult]:
    """Best graded attempt per student for one quiz."""
    attempts = get_attempts(client, cmid)
    by_student: dict[str, list[QuizAttempt]] = {}
    for a in attempts:
        key = str(a["user_id"]) if a["user_id"] is not None else f"email:{a['email']}"
        by_student.setdefault(key, []).append(a)

    out: list[QuizResult] = []
    for entries in by_student.values():
        graded = [(a, _grade_value(a["grade"])) for a in entries]
        graded_with_value = [(a, v) for a, v in graded if v is not None]
        if graded_with_value:
            best_a, _ = max(graded_with_value, key=lambda x: x[1] or 0.0)
            best_grade = best_a["grade"]
        else:
            best_a = entries[0]
            best_grade = "-"
        out.append({
            "cmid": cmid,
            "user_id": best_a["user_id"],
            "fullname": best_a["fullname"],
            "email": best_a["email"],
            "attempts": len(entries),
            "best_grade": best_grade,
            "max_grade": best_a["max_grade"],
        })
    out.sort(key=lambda r: r["fullname"].lower())
    return out

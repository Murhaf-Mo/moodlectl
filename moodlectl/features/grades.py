from __future__ import annotations

import re

from moodlectl.types import CourseId, GradeReport, GradeStats, MoodleClientProtocol


def get_grade_report(
        client: MoodleClientProtocol,
        course_id: CourseId,
        name: str = "",
        include_hidden: bool = False,
) -> GradeReport:
    """Return grade report for a course, optionally filtered by student name.

    name: case-insensitive partial match on fullname.
    include_hidden: if False (default), drop columns whose backing activity is
      hidden from students. The Course total column is always kept.
    """
    report = client.get_grade_report(course_id)

    if name:
        needle = name.lower()
        report["rows"] = [r for r in report["rows"] if needle in str(r["fullname"]).lower()]

    if not include_hidden:
        hidden_cmids = {
            mod["cmid"]
            for sec in client.get_course_sections(course_id)
            for mod in sec["modules"]
            if not mod.get("visible", True)
        }
        if hidden_cmids:
            cmids = report.get("column_cmids", {})
            drop = {col for col, cmid in cmids.items() if cmid in hidden_cmids}
            if drop:
                report["columns"] = [c for c in report["columns"] if c not in drop]
                report["rows"] = [
                    {k: v for k, v in r.items() if k not in drop} for r in report["rows"]
                ]

    return report


def shorten_columns(columns: list[str], max_len: int = 22) -> dict[str, str]:
    """Return {original_col: short_col} mapping for table display.

    Strips Arabic text (parenthesised non-ASCII blocks) and truncates to max_len.
    Used by the grades show command to fit wide grade tables in the terminal.
    """
    mapping: dict[str, str] = {}
    for col in columns:
        # Remove Arabic/non-ASCII parenthesised suffixes like (البرمجة...)
        short = re.sub(r"\s*\([^\x00-\x7F]+\)", "", col).strip()
        if len(short) > max_len:
            short = short[:max_len - 1] + "…"
        mapping[col] = short
    return mapping


def compute_stats(report: GradeReport) -> GradeStats:
    """Compute grade statistics for the course total column.

    Parses numeric values from the last column (Course total) of a grade report.
    Returns:
      {column, count, mean, median, std_dev, min, max}

    Values like "75.00 (75.00 %)" are handled — only the first number is used.
    Returns an empty GradeStats if no numeric grades are found.
    """
    import statistics

    rows = report.get("rows", [])
    columns = report.get("columns", [])
    if not rows or not columns:
        return {"column": "", "count": 0, "mean": 0.0, "median": 0.0, "std_dev": 0.0, "min": 0.0, "max": 0.0}

    # The last column is always the Course total
    total_col = columns[-1]

    values: list[float] = []
    for row in rows:
        raw = row.get(total_col, "-")
        m = re.match(r"([\d.]+)", str(raw))
        if m:
            try:
                values.append(float(m.group(1)))
            except ValueError:
                pass

    if not values:
        return {"column": total_col, "count": 0, "mean": 0.0, "median": 0.0, "std_dev": 0.0, "min": 0.0, "max": 0.0}

    return {
        "column": total_col,
        "count": len(values),
        "mean": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "std_dev": round(statistics.stdev(values), 2) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }

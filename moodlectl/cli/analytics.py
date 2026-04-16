"""Analytics command group — grade and submission visualisations.

Requires the analytics optional dependencies:
  pip install moodlectl[analytics]

Each command checks for those dependencies before making any API calls.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from moodlectl.output.charts import ANALYTICS_AVAILABLE as _CHARTS_AVAILABLE

app = typer.Typer(
    name="analytics",
    help=(
        "Grade and submission analytics.\n\n"
        "Charts render directly in the terminal by default.\n"
        "Pass --save <file.png> to write a PNG/PDF file instead.\n\n"
        "Requires:  pip install moodlectl[analytics]"
    ),
    no_args_is_help=True,
)

_console = Console(legacy_windows=False)


def _check_deps() -> None:
    if not _CHARTS_AVAILABLE:
        _console.print(
            "[red]Analytics dependencies are not installed.[/red]\n"
            "Run:  [bold]pip install moodlectl\\[analytics][/bold]"
        )
        raise typer.Exit(1)


def _client_and_course(course_id: int):  # type: ignore[return]
    from moodlectl.client import MoodleClient
    from moodlectl.config import Config
    from moodlectl.types import CourseId

    client = MoodleClient.from_config(Config.load())
    return client, CourseId(course_id)


# ---------------------------------------------------------------------------
# grades-dist
# ---------------------------------------------------------------------------

@app.command("grades-dist")
def grades_dist(
        course_id: int = typer.Option(..., "--course", "-c", help="Moodle course ID"),
        item: Optional[str] = typer.Option(None, "--item", help="Grade item column name (default: Course total)"),
        bins: int = typer.Option(10, "--bins", help="Number of histogram bins"),
        save: Optional[str] = typer.Option(None, "--save", help="File path to save chart (e.g. dist.png)"),
        fmt: str = typer.Option("png", "--fmt", help="File format: png or pdf"),
) -> None:
    """Grade distribution histogram for a course.

    Shows how grades are spread — a bimodal curve suggests the assessment
    separates two distinct groups and the rubric may need revision.

    Examples:
      moodlectl analytics grades-dist --course 123
      moodlectl analytics grades-dist --course 123 --save dist.png
    """
    _check_deps()
    client, cid = _client_and_course(course_id)

    from moodlectl.features.analytics import get_grade_distribution
    from moodlectl.features.grades import compute_stats
    from moodlectl.output.charts import plot_grade_histogram
    from moodlectl.output.formatters import print_table

    with _console.status("Fetching grade report…"):
        report = client.get_grade_report(cid)
        grades, col = get_grade_distribution(client, cid, item)
        stats = compute_stats(report)

    if not grades:
        _console.print(f"[yellow]No numeric grades found in column '{col}'.[/yellow]")
        raise typer.Exit()

    _console.print(f"\n[bold]Grade stats — {col}[/bold]")
    print_table(
        [stats],  # type: ignore[list-item]
        ["count", "mean", "median", "std_dev", "min", "max"],
    )
    _console.print()
    plot_grade_histogram(grades, col, bins=bins, save_path=save, fmt=fmt)


# ---------------------------------------------------------------------------
# grades-boxplot
# ---------------------------------------------------------------------------

@app.command("grades-boxplot")
def grades_boxplot(
        course_id: int = typer.Option(..., "--course", "-c", help="Moodle course ID"),
        save: Optional[str] = typer.Option(None, "--save", help="File path to save chart"),
        fmt: str = typer.Option("png", "--fmt", help="File format: png or pdf"),
) -> None:
    """Box plot of grade spread per assignment.

    Identifies which assignments were hardest so you can decide whether to
    adjust weights or offer re-submissions.

    Examples:
      moodlectl analytics grades-boxplot --course 123
      moodlectl analytics grades-boxplot --course 123 --save boxplot.pdf --fmt pdf
    """
    _check_deps()
    client, cid = _client_and_course(course_id)

    from moodlectl.features.analytics import get_per_assignment_grades
    from moodlectl.output.charts import plot_grade_boxplot

    with _console.status("Fetching grade report…"):
        data = get_per_assignment_grades(client, cid)

    if not data:
        _console.print("[yellow]No assignment grade data found.[/yellow]")
        raise typer.Exit()

    courses = client.get_courses()
    course_name = next((c["fullname"] for c in courses if c["id"] == cid), str(cid))
    plot_grade_boxplot(data, course_name, save_path=save, fmt=fmt)


# ---------------------------------------------------------------------------
# letter-grades
# ---------------------------------------------------------------------------

@app.command("letter-grades")
def letter_grades(
        course_id: int = typer.Option(..., "--course", "-c", help="Moodle course ID"),
        grade_max: Optional[float] = typer.Option(None, "--grade-max", help="Maximum possible grade (auto-detected from report if omitted)"),
        save: Optional[str] = typer.Option(None, "--save", help="File path to save chart"),
        fmt: str = typer.Option("png", "--fmt", help="File format: png or pdf"),
) -> None:
    """Letter grade bar chart (A / B / C / D / F).

    grade-max is auto-detected from the highest grade in the report when not
    specified — so a course graded out of 40 is bucketed correctly without any flags.

    Examples:
      moodlectl analytics letter-grades --course 123
      moodlectl analytics letter-grades --course 123 --grade-max 50
    """
    _check_deps()
    client, cid = _client_and_course(course_id)

    from moodlectl.features.analytics import get_grade_distribution
    from moodlectl.features.grades import compute_stats
    from moodlectl.output.charts import bucket_grades, plot_letter_grade_bars
    from moodlectl.output.formatters import print_table

    with _console.status("Fetching grade report…"):
        report = client.get_grade_report(cid)
        grades, col = get_grade_distribution(client, cid)
        stats = compute_stats(report)

    if not grades:
        _console.print("[yellow]No numeric grades found.[/yellow]")
        raise typer.Exit()

    # Auto-detect grade_max from the actual maximum grade in the report
    effective_max = grade_max if grade_max is not None else (stats["max"] if stats["count"] else 100.0)

    courses = client.get_courses()
    course_name = next((c["fullname"] for c in courses if c["id"] == cid), str(cid))

    buckets = bucket_grades(grades, effective_max)
    total = len(grades)
    table_data = [
        {"grade": k, "count": v, "percent": f"{v/total*100:.1f}%" if total else "0%"}
        for k, v in buckets.items()
    ]
    _console.print(f"\n[bold]Letter grades — {col}[/bold]  (n={total}, max={effective_max})")
    print_table(table_data, ["grade", "count", "percent"])
    _console.print()
    plot_letter_grade_bars(grades, course_name, grade_max=effective_max, save_path=save, fmt=fmt)


# ---------------------------------------------------------------------------
# submission-status
# ---------------------------------------------------------------------------

@app.command("submission-status")
def submission_status(
        course_id: int = typer.Option(..., "--course", "-c", help="Moodle course ID"),
        assignment_id: Optional[int] = typer.Option(None, "--assignment-id", help="Limit to one assignment (cmid)"),
        save: Optional[str] = typer.Option(None, "--save", help="File path to save chart"),
        fmt: str = typer.Option("png", "--fmt", help="File format: png or pdf"),
) -> None:
    """Submission status chart — submitted / ungraded / missing.

    Use this to decide which assignment to grade first and who to remind.

    Examples:
      moodlectl analytics submission-status --course 123
      moodlectl analytics submission-status --course 123 --assignment-id 456
    """
    _check_deps()
    client, cid = _client_and_course(course_id)

    from moodlectl.features.analytics import get_submission_summary
    from moodlectl.output.charts import plot_submission_rate_by_assignment, plot_submission_status
    from moodlectl.output.formatters import print_table

    summaries = get_submission_summary(client, cid)

    if not summaries:
        _console.print("[yellow]No submission data found.[/yellow]")
        raise typer.Exit()

    if assignment_id is not None:
        from moodlectl.types import Cmid
        filtered = [s for s in summaries if s["cmid"] == Cmid(assignment_id)]
        if not filtered:
            _console.print(f"[yellow]Assignment {assignment_id} not found in course.[/yellow]")
            raise typer.Exit()
        print_table(
            filtered,  # type: ignore[arg-type]
            ["name", "submitted", "ungraded", "missing", "total"],
        )
        plot_submission_status(filtered[0], save_path=save, fmt=fmt)
    else:
        print_table(
            summaries,  # type: ignore[arg-type]
            ["name", "submitted", "ungraded", "missing", "total"],
        )
        courses = client.get_courses()
        course_name = next((c["fullname"] for c in courses if c["id"] == cid), str(cid))
        plot_submission_rate_by_assignment(summaries, course_name, save_path=save, fmt=fmt)


# ---------------------------------------------------------------------------
# grade-progression
# ---------------------------------------------------------------------------

@app.command("grade-progression")
def grade_progression(
        course_id: int = typer.Option(..., "--course", "-c", help="Moodle course ID"),
        save: Optional[str] = typer.Option(None, "--save", help="File path to save chart"),
        fmt: str = typer.Option("png", "--fmt", help="File format: png or pdf"),
) -> None:
    """Line chart of cohort mean and median grades across assignments.

    A declining trend means later assignments are harder or the cohort is
    losing engagement — consider scheduling a review session.

    Examples:
      moodlectl analytics grade-progression --course 123
      moodlectl analytics grade-progression --course 123 --save progress.png
    """
    _check_deps()
    client, cid = _client_and_course(course_id)

    from moodlectl.features.analytics import get_per_assignment_grades
    from moodlectl.output.charts import plot_grade_progression

    with _console.status("Fetching grade report…"):
        data = get_per_assignment_grades(client, cid)

    if not data:
        _console.print("[yellow]No assignment grade data found.[/yellow]")
        raise typer.Exit()

    courses = client.get_courses()
    course_name = next((c["fullname"] for c in courses if c["id"] == cid), str(cid))
    plot_grade_progression(data, course_name, save_path=save, fmt=fmt)


# ---------------------------------------------------------------------------
# at-risk
# ---------------------------------------------------------------------------

@app.command("at-risk")
def at_risk(
        course_id: int = typer.Option(..., "--course", "-c", help="Moodle course ID"),
        threshold: float = typer.Option(60.0, "--threshold", help="Percentage threshold (0-100) below which a student is at-risk (applied against course max)"),
) -> None:
    """List students who need immediate attention.

    --threshold is a percentage (default 60%). It is automatically scaled to the
    actual course total maximum — so a course out of 40 uses 24.0 as the cutoff
    when threshold=60, not 60.0.

    Flags students who are below the threshold AND/OR have missing or ungraded
    submissions. Each row shows the suggested action:
      remind — student hasn't submitted; send them a message
      grade  — submission is waiting for your grade
      both   — both of the above

    This is the most actionable output in the analytics group.

    Examples:
      moodlectl analytics at-risk --course 123
      moodlectl analytics at-risk --course 123 --threshold 70
    """
    client, cid = _client_and_course(course_id)

    from moodlectl.features.analytics import get_at_risk_students
    from moodlectl.features.grades import compute_stats
    from moodlectl.output.formatters import print_table

    with _console.status(f"Analysing course {course_id}…"):
        report = client.get_grade_report(cid)
        stats = compute_stats(report)
        # Scale percentage threshold to actual course max
        grade_max = stats["max"] if stats["count"] else 100.0
        absolute_threshold = grade_max * threshold / 100.0
        students = get_at_risk_students(client, cid, threshold=absolute_threshold)

    _console.print(
        f"[dim]Threshold: {threshold}% of {grade_max} = {absolute_threshold:.1f}[/dim]"
    )

    if not students:
        _console.print(f"[green]No at-risk students found (threshold={threshold}).[/green]")
        raise typer.Exit()

    _console.print(
        f"\n[bold red]{len(students)} at-risk student(s)[/bold red] "
        f"(threshold={threshold})\n"
    )
    print_table(
        students,  # type: ignore[arg-type]
        ["fullname", "email", "course_total", "missing_count", "ungraded_count", "action"],
    )


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

@app.command("summary")
def summary(
        course_id: int = typer.Option(..., "--course", "-c", help="Moodle course ID"),
        save_dir: Optional[str] = typer.Option(None, "--save-dir", help="Directory to write all charts as PNG files"),
) -> None:
    """Full analytics report: all charts in one command.

    Runs grade-dist, letter-grades, submission-status, and grade-progression
    in sequence. Pass --save-dir to write all charts as PNG files.

    Examples:
      moodlectl analytics summary --course 123
      moodlectl analytics summary --course 123 --save-dir ./reports/
    """
    _check_deps()
    client, cid = _client_and_course(course_id)

    from moodlectl.features.analytics import (
        get_at_risk_students,
        get_grade_distribution,
        get_per_assignment_grades,
        get_submission_summary,
    )
    from moodlectl.features.grades import compute_stats
    from moodlectl.output.charts import (
        plot_grade_histogram,
        plot_grade_progression,
        plot_letter_grade_bars,
        plot_submission_rate_by_assignment,
    )
    from moodlectl.output.formatters import print_table

    outdir = Path(save_dir) if save_dir else None
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)

    courses = client.get_courses()
    course_name = next((c["fullname"] for c in courses if c["id"] == cid), str(cid))

    _console.rule(f"[bold]Analytics — {course_name}[/bold]")

    # 1. Grade distribution
    _console.print("\n[bold]1 / 5 · Grade Distribution[/bold]")
    with _console.status("Fetching grade report…"):
        report = client.get_grade_report(cid)
        grades, col = get_grade_distribution(client, cid)
        stats = compute_stats(report)

    if grades:
        _console.print(f"[dim]Column: {col}[/dim]")
        print_table([stats], ["count", "mean", "median", "std_dev", "min", "max"])  # type: ignore[list-item]
        _save = str(outdir / "1_grade_dist.png") if outdir else None
        plot_grade_histogram(grades, course_name, save_path=_save)

    # 2. Letter grades
    _console.print("\n[bold]2 / 5 · Letter Grades[/bold]")
    if grades:
        from moodlectl.output.charts import bucket_grades
        auto_max = stats["max"] if stats["count"] else 100.0
        buckets = bucket_grades(grades, auto_max)
        total = len(grades)
        print_table(
            [{"grade": k, "count": v, "percent": f"{v/total*100:.1f}%"} for k, v in buckets.items()],
            ["grade", "count", "percent"],
        )
        _save = str(outdir / "2_letter_grades.png") if outdir else None
        plot_letter_grade_bars(grades, course_name, grade_max=auto_max, save_path=_save)

    # 3. Submission status
    _console.print("\n[bold]3 / 5 · Submission Status[/bold]")
    summaries = get_submission_summary(client, cid)
    if summaries:
        print_table(summaries, ["name", "submitted", "ungraded", "missing", "total"])  # type: ignore[arg-type]
        _save = str(outdir / "3_submission_status.png") if outdir else None
        plot_submission_rate_by_assignment(summaries, course_name, save_path=_save)

    # 4. Grade progression
    _console.print("\n[bold]4 / 5 · Grade Progression[/bold]")
    with _console.status("Fetching per-assignment grades…"):
        assignment_grades = get_per_assignment_grades(client, cid)
    if assignment_grades:
        _save = str(outdir / "4_grade_progression.png") if outdir else None
        plot_grade_progression(assignment_grades, course_name, save_path=_save)

    # 5. At-risk students
    _console.print("\n[bold]5 / 5 · At-Risk Students[/bold]")
    with _console.status("Cross-referencing grades and submissions…"):
        at_risk_students = get_at_risk_students(client, cid)
    if at_risk_students:
        _console.print(f"[bold red]{len(at_risk_students)} at-risk student(s):[/bold red]")
        print_table(
            at_risk_students,  # type: ignore[arg-type]
            ["fullname", "email", "course_total", "missing_count", "ungraded_count", "action"],
        )
    else:
        _console.print("[green]No at-risk students found.[/green]")

    if outdir:
        _console.print(f"\n[green]Charts saved to:[/green] [bold]{outdir.resolve()}[/bold]")
    _console.rule()

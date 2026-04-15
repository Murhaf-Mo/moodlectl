"""Chart rendering for the analytics command group.

Each public function has two rendering paths:
  save_path=None  → terminal chart via plotext (inline, no GUI required)
  save_path=str   → PNG/PDF file via matplotlib Agg backend (headless)

Import guard: if plotext or matplotlib are not installed the module still imports,
but every public function raises RuntimeError with the install hint.
"""
from __future__ import annotations

import os
from typing import Any

from moodlectl.types import AssignmentGrades, SubmissionSummary

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------

# Initialise to None so pyright considers them always-bound.
# They are overwritten with the real modules when the import succeeds.
# _require() guarantees they are never None at the call sites.
_pt: Any = None
_mpl: Any = None

ANALYTICS_AVAILABLE: bool = False

try:
    import plotext as _pt  # type: ignore[reportMissingTypeStubs]
    import matplotlib as _mpl
    _mpl.use("Agg")  # must be set before importing pyplot
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
    ANALYTICS_AVAILABLE = True  # type: ignore[reportConstantRedefinition]
except ImportError:
    pass


def _require() -> None:
    if not ANALYTICS_AVAILABLE:
        raise RuntimeError(
            "Analytics dependencies are not installed.\n"
            "Run:  pip install moodlectl[analytics]"
        )


# ---------------------------------------------------------------------------
# Internal matplotlib helpers
# ---------------------------------------------------------------------------

def _new_fig(title: str, xlabel: str, ylabel: str) -> tuple[Figure, Axes]:  # type: ignore[type-arg]
    """Create a consistently styled figure and axes."""
    import matplotlib.pyplot as _plt  # local re-import avoids F821 when _AVAILABLE=False
    _mpl.rcParams["font.family"] = "DejaVu Sans"  # broad Unicode coverage

    fig, ax = _plt.subplots(figsize=(10, 5))
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    return fig, ax  # type: ignore[return-value]


def _save_fig(fig: Figure, save_path: str, fmt: str) -> None:  # type: ignore[type-arg]
    import matplotlib.pyplot as _plt
    fig.savefig(save_path, format=fmt, bbox_inches="tight", dpi=150)
    _plt.close(fig)


# ---------------------------------------------------------------------------
# Minimum terminal width before falling back to a text summary
# ---------------------------------------------------------------------------

_MIN_WIDTH = 60


def _terminal_wide_enough() -> bool:
    try:
        return os.get_terminal_size().columns >= _MIN_WIDTH
    except OSError:
        return True  # non-terminal (e.g. piped) — let plotext handle it


# ---------------------------------------------------------------------------
# Public chart functions
# ---------------------------------------------------------------------------

def plot_grade_histogram(
        grades: list[float],
        course_name: str,
        bins: int = 10,
        save_path: str | None = None,
        fmt: str = "png",
) -> None:
    """Histogram of grade values.

    Shows grade distribution — useful for spotting bimodal curves or skew that
    suggests the rubric needs adjustment.
    """
    _require()
    if not grades:
        print("No numeric grades to plot.")
        return

    if save_path:
        fig, ax = _new_fig(
            f"Grade Distribution — {course_name}",
            "Grade", "Number of Students",
        )
        ax.hist(grades, bins=bins, color="#4C72B0", edgecolor="white", linewidth=0.6)
        _save_fig(fig, save_path, fmt)
        print(f"Saved: {save_path}")
    else:
        if not _terminal_wide_enough():
            _text_summary("Grade Distribution", grades)
            return
        _pt.clf()
        _pt.hist(grades, bins)
        _pt.title(f"Grade Distribution — {course_name}")
        _pt.xlabel("Grade")
        _pt.ylabel("Count")
        _pt.show()


def plot_grade_boxplot(
        data: list[AssignmentGrades],
        course_name: str,
        save_path: str | None = None,
        fmt: str = "png",
) -> None:
    """Box plot comparing grade spread across assignments.

    Identifies which assignments were hardest (low median, many outliers).
    """
    _require()
    if not data:
        print("No assignment grade data to plot.")
        return

    labels = [d["assignment"][:30] for d in data]
    values = [d["grades"] for d in data]

    if save_path:
        fig, ax = _new_fig(
            f"Grade Distribution by Assignment — {course_name}",
            "Grade", "Assignment",
        )
        ax.boxplot(
            values, vert=False, labels=labels, patch_artist=True,  # type: ignore[reportCallIssue]
            boxprops=dict(facecolor="#4C72B0", alpha=0.6),
        )
        fig.set_size_inches(10, max(4, len(labels) * 0.5 + 1))
        _save_fig(fig, save_path, fmt)
        print(f"Saved: {save_path}")
    else:
        if not _terminal_wide_enough():
            for d in data:
                g = d["grades"]
                print(f"  {d['assignment'][:40]:<40}  "
                      f"min={min(g):.1f}  median={sorted(g)[len(g)//2]:.1f}  max={max(g):.1f}")
            return
        # plotext has no native boxplot — render as bar chart of medians with range annotation
        _pt.clf()
        medians = [sorted(g)[len(g) // 2] for g in values]
        _pt.bar(labels, medians, orientation="h")
        _pt.title(f"Median Grade by Assignment — {course_name}")
        _pt.xlabel("Median Grade")
        _pt.show()


def plot_letter_grade_bars(
        grades: list[float],
        course_name: str,
        grade_max: float = 100.0,
        save_path: str | None = None,
        fmt: str = "png",
) -> None:
    """Bar chart of letter-grade bucket counts (A/B/C/D/F).

    Useful for accreditation reporting and deciding where to focus support.
    """
    _require()
    if not grades:
        print("No numeric grades to plot.")
        return

    buckets = bucket_grades(grades, grade_max)
    letters = list(buckets.keys())
    counts = list(buckets.values())
    colors = ["#2ecc71", "#3498db", "#f39c12", "#e67e22", "#e74c3c"]

    if save_path:
        fig, ax = _new_fig(
            f"Letter Grade Distribution — {course_name}",
            "Letter Grade", "Number of Students",
        )
        bars = ax.bar(letters, counts, color=colors, edgecolor="white", linewidth=0.6)
        for bar, count in zip(bars, counts):  # type: ignore[reportUnknownVariableType]
            if count:
                ax.text(
                    bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.2,  # type: ignore[reportUnknownArgumentType]
                    str(count), ha="center", va="bottom", fontsize=10,
                )
        _save_fig(fig, save_path, fmt)
        print(f"Saved: {save_path}")
    else:
        if not _terminal_wide_enough():
            for letter, count in buckets.items():
                print(f"  {letter}: {count}")
            return
        _pt.clf()
        _pt.bar(letters, counts)
        _pt.title(f"Letter Grade Distribution — {course_name}")
        _pt.xlabel("Letter Grade")
        _pt.ylabel("Count")
        _pt.show()


def plot_submission_status(
        summary: SubmissionSummary,
        save_path: str | None = None,
        fmt: str = "png",
) -> None:
    """Stacked bar showing submitted / ungraded / missing for one assignment."""
    _require()

    name = summary["name"]
    submitted_graded = summary["submitted"] - summary["ungraded"]
    ungraded = summary["ungraded"]
    missing = summary["missing"]

    categories = ["Graded", "Ungraded", "Missing"]
    counts = [submitted_graded, ungraded, missing]

    if save_path:
        fig, ax = _new_fig(f"Submission Status — {name}", "", "")
        ax.barh([""], [submitted_graded], color="#2ecc71", label="Graded")
        ax.barh([""], [ungraded], left=[submitted_graded], color="#f39c12", label="Ungraded")
        ax.barh([""], [missing], left=[submitted_graded + ungraded], color="#e74c3c", label="Missing")
        ax.legend(loc="upper right")
        ax.set_xlabel("Students")
        ax.set_xlim(0, summary["total"] or 1)
        _save_fig(fig, save_path, fmt)
        print(f"Saved: {save_path}")
    else:
        _pt.clf()
        _pt.bar(categories, counts)
        _pt.title(f"Submission Status — {name[:50]}")
        _pt.show()


def plot_submission_rate_by_assignment(
        data: list[SubmissionSummary],
        course_name: str,
        save_path: str | None = None,
        fmt: str = "png",
) -> None:
    """Grouped bar chart: submitted vs. missing per assignment.

    Shows which assignments have low engagement — a signal to send reminders.
    """
    _require()
    if not data:
        print("No submission data to plot.")
        return

    names = [d["name"][:25] for d in data]
    submitted = [d["submitted"] for d in data]
    missing = [d["missing"] for d in data]

    if save_path:
        import numpy as _np
        fig, ax = _new_fig(
            f"Submission Rate by Assignment — {course_name}",
            "Assignment", "Students",
        )
        x = _np.arange(len(names))
        w = 0.35
        ax.bar(x - w / 2, submitted, w, label="Submitted", color="#2ecc71")
        ax.bar(x + w / 2, missing, w, label="Missing", color="#e74c3c")
        ax.set_xticks(x)
        ax.set_xticklabels(names, rotation=30, ha="right")
        ax.legend()
        fig.set_size_inches(max(8, len(names) * 1.2), 5)
        _save_fig(fig, save_path, fmt)
        print(f"Saved: {save_path}")
    else:
        if not _terminal_wide_enough():
            for d in data:
                print(f"  {d['name'][:40]:<40}  submitted={d['submitted']}  missing={d['missing']}")
            return
        _pt.clf()
        _pt.multiple_bar(names, [submitted, missing], labels=["Submitted", "Missing"])
        _pt.title(f"Submission Rate — {course_name}")
        _pt.show()


def plot_grade_progression(
        data: list[AssignmentGrades],
        course_name: str,
        save_path: str | None = None,
        fmt: str = "png",
) -> None:
    """Line chart of cohort mean and median across assignments (in grade-report order).

    A declining trend signals that later assignments are harder or that the cohort
    is losing engagement — either way, action is warranted.
    """
    _require()
    if not data:
        print("No assignment grade data to plot.")
        return

    import statistics

    labels = [d["assignment"][:25] for d in data]
    means = [round(statistics.mean(d["grades"]), 2) for d in data]
    medians = [round(statistics.median(d["grades"]), 2) for d in data]

    if save_path:
        fig, ax = _new_fig(
            f"Grade Progression — {course_name}",
            "Assignment", "Grade",
        )
        ax.plot(range(len(labels)), means, marker="o", label="Mean", color="#4C72B0")
        ax.plot(range(len(labels)), medians, marker="s", linestyle="--", label="Median", color="#DD8452")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=30, ha="right")
        ax.legend()
        fig.set_size_inches(max(8, len(labels) * 1.2), 5)
        _save_fig(fig, save_path, fmt)
        print(f"Saved: {save_path}")
    else:
        if not _terminal_wide_enough():
            for label, mean, median in zip(labels, means, medians):
                print(f"  {label:<30}  mean={mean}  median={median}")
            return
        # plotext interprets string x-values as dates — use integer indices instead
        xs = list(range(1, len(labels) + 1))
        _pt.clf()
        _pt.plot(xs, means, label="Mean")
        _pt.plot(xs, medians, label="Median")
        _pt.xticks(xs, labels)
        _pt.title(f"Grade Progression — {course_name}")
        _pt.xlabel("Assignment")
        _pt.ylabel("Grade")
        _pt.show()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def bucket_grades(grades: list[float], grade_max: float) -> dict[str, int]:
    """Bucket grades into A/B/C/D/F based on percentage of grade_max."""
    buckets: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    for g in grades:
        pct = (g / grade_max * 100) if grade_max else 0
        if pct >= 90:
            buckets["A"] += 1
        elif pct >= 80:
            buckets["B"] += 1
        elif pct >= 70:
            buckets["C"] += 1
        elif pct >= 60:
            buckets["D"] += 1
        else:
            buckets["F"] += 1
    return buckets


def _text_summary(label: str, grades: list[float]) -> None:
    """Fallback text output when terminal is too narrow for a chart."""
    import statistics
    print(f"{label}: n={len(grades)}  mean={statistics.mean(grades):.1f}  "
          f"median={statistics.median(grades):.1f}  "
          f"min={min(grades):.1f}  max={max(grades):.1f}")

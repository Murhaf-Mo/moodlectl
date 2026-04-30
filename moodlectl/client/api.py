from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, cast
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag

from moodlectl.client.base import MoodleClientBase
from moodlectl.types import (
    JSON,
    AssignmentMeta,
    Cmid,
    Course,
    CourseId,
    CourseModule,
    CourseSection,
    Discussion,
    FileRef,
    ForumPost,
    FormFields,
    GradeReport,
    Participant,
    SectionId,
    Submission,
    UserId,
)

# Shown whenever an HTTP response redirects to the login page.
_SESSION_EXPIRED = "Re-login in your browser and update MOODLE_SESSION in .env"


# ── BeautifulSoup attribute helpers ──────────────────────────────────────────
# BS4's type stubs type tag attributes as str | list[str] (_AttributeValue).
# These helpers narrow the result to the concrete types we actually need.

def _attr(tag: Tag, name: str, default: str = "") -> str:
    """Return a tag attribute as a plain string."""
    val = tag.get(name)
    return str(val) if val is not None else default


def _int_attr(tag: Tag, name: str) -> int:
    """Return a tag attribute as an integer (raises ValueError if not numeric)."""
    return int(str(tag[name]))


def _classes(tag: Tag) -> list[str]:
    """Return the tag's class list as a list of strings."""
    val = tag.get("class")
    if isinstance(val, list):
        return [str(c) for c in val]
    return []


# ── Module settings helpers ───────────────────────────────────────────────────

def _parse_datetime(form: dict[str, str], prefix: str, always_on: bool = False) -> str:
    """Parse a Moodle date-group (prefix[day/month/year/hour/minute]) to 'YYYY-MM-DD HH:MM'.

    always_on=True  — no [enabled] checkbox (e.g. course startdate); parse if [day] present.
    always_on=False — require [enabled] to be present and truthy (module dates, course enddate).
                      An absent [enabled] key means the checkbox is unchecked → return "".
    """
    if always_on:
        if f"{prefix}[day]" not in form:
            return ""
    else:
        if not form.get(f"{prefix}[enabled]", ""):
            return ""
    try:
        day = int(form.get(f"{prefix}[day]", "1"))
        month = int(form.get(f"{prefix}[month]", "1"))
        year = int(form.get(f"{prefix}[year]", "2000"))
        hour = int(form.get(f"{prefix}[hour]", "0"))
        minute = int(form.get(f"{prefix}[minute]", "0"))
        return datetime(year, month, day, hour, minute).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return ""


def _datetime_to_form(value: str, prefix: str) -> dict[str, str]:
    """Convert 'YYYY-MM-DD HH:MM' back to Moodle date-group form fields."""
    try:
        dt = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError(f"Date must be 'YYYY-MM-DD HH:MM', got {value!r}")
    return {
        f"{prefix}[enabled]": "1",
        f"{prefix}[day]": str(dt.day),
        f"{prefix}[month]": str(dt.month),
        f"{prefix}[year]": str(dt.year),
        f"{prefix}[hour]": str(dt.hour),
        f"{prefix}[minute]": str(dt.minute),
    }


_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')


def _parse_duration_mins(form: dict[str, str], prefix: str) -> int:
    """Parse a Moodle compound duration field (prefix[number] + prefix[timeunit]) to total minutes.

    When Moodle renders the field with optional=True it adds a prefix[enabled] checkbox.
    If that key is present in the form but falsy (unchecked), the duration is disabled → 0.
    """
    enabled_key = f"{prefix}[enabled]"
    if enabled_key in form and not form[enabled_key]:
        return 0
    try:
        number = int(form.get(f"{prefix}[number]", "0"))
        timeunit = int(form.get(f"{prefix}[timeunit]", "60"))
        return number * timeunit // 60
    except (ValueError, TypeError):
        return 0


def _duration_mins_to_form(mins: int, prefix: str) -> dict[str, str]:
    """Convert total minutes back to Moodle compound duration form fields.

    Sets prefix[enabled]=1 so Moodle activates the field when the value is non-zero.
    """
    if mins:
        return {
            f"{prefix}[enabled]": "1",
            f"{prefix}[number]": str(int(mins)),
            f"{prefix}[timeunit]": "60",
        }
    return {
        f"{prefix}[enabled]": "",
        f"{prefix}[number]": "0",
        f"{prefix}[timeunit]": "60",
    }


# ── Comprehensive curated settings schema ─────────────────────────────────────
#
# type_hint: "str" | "int" | "float" | "datetime" | "duration_mins" | "tags"
#   datetime      — "YYYY-MM-DD HH:MM"; uses prefix[enabled/day/...] form group
#   duration_mins — int total minutes; uses prefix[number]+prefix[timeunit] form fields
#   tags          — list of strings; form fields are tags[0], tags[1], ...
#   int           — defaults to 0 when absent (handles unchecked checkboxes/radios)
#
# COMMON fields appear on every module type.
# Type-specific schemas are merged with COMMON when building settings.
#
_COMMON_SCHEMA: dict[str, tuple[str, str]] = {
    # General
    "id_number": ("cmidnumber", "str"),
    "show_description": ("showdescription", "int"),
    "force_language": ("lang", "str"),
    # Groups
    "group_mode": ("groupmode", "int"),
    "grouping": ("groupingid", "int"),
    # Tags
    "tags": ("tags", "tags"),
    # Competencies
    "competency_rule": ("competency_rule", "int"),
    # Completion tracking
    "completion": ("completion", "int"),  # 0=none 1=manual 2=auto
    "completion_on_view": ("completionview", "int"),
    "completion_on_grade": ("completionusegrade", "int"),
    "completion_pass_grade": ("completionpassgrade", "int"),
    "completion_expected": ("completionexpected", "datetime"),
}

_SETTINGS_SCHEMA: dict[str, dict[str, tuple[str, str]]] = {
    "assign": {
        **_COMMON_SCHEMA,
        "description": ("introeditor[text]", "str"),
        "due_date": ("duedate", "datetime"),
        "available_from": ("allowsubmissionsfromdate", "datetime"),
        "cut_off": ("cutoffdate", "datetime"),
        "grading_due": ("gradingduedate", "datetime"),
        "max_grade": ("grade[modgrade_point]", "float"),
        "grade_pass": ("gradepass", "float"),
        "grade_category": ("gradecat", "int"),
        "submission_drafts": ("submissiondrafts", "int"),
        "require_statement": ("requiresubmissionstatement", "int"),
        "online_text_enabled": ("assignsubmission_onlinetext_enabled", "int"),
        "file_enabled": ("assignsubmission_file_enabled", "int"),
        "max_files": ("assignsubmission_file_maxfiles", "int"),
        "max_file_size": ("assignsubmission_file_maxsizebytes", "int"),
        "allowed_file_types": ("assignsubmission_file_filetypes[filetypes]", "str"),
        "inline_comments": ("assignfeedback_comments_commentinline", "int"),
        "notify_graders": ("sendnotifications", "int"),
        "notify_graders_late": ("sendlatenotifications", "int"),
        "notify_students": ("sendstudentnotifications", "int"),
        "blind_marking": ("blindmarking", "int"),
        "hide_grader": ("hidegrader", "int"),
        "marking_workflow": ("markingworkflow", "int"),
        "marking_allocation": ("markingallocation", "int"),
        "team_submission": ("teamsubmission", "int"),
        "reopen_attempts": ("attemptreopenmethod", "str"),
        "max_attempts": ("maxattempts", "int"),
        "completion_on_submit": ("completionsubmit", "int"),
        "grading_method": ("advancedgradingmethod_submissions", "str"),
        # ── Extra keys consumed by `assignments create` (don't overlap above) ──
        "show_description_on_course_page": ("showdescription", "int"),
        "instructions": ("activityeditor[text]", "str"),
        "always_show_description": ("alwaysshowdescription", "int"),
        "word_limit": ("assignsubmission_onlinetext_wordlimit", "int"),
        "word_limit_enabled": ("assignsubmission_onlinetext_wordlimit_enabled", "int"),
        "feedback_comments": ("assignfeedback_comments_enabled", "int"),
        "feedback_file": ("assignfeedback_file_enabled", "int"),
        "feedback_offline_grading_worksheet": ("assignfeedback_offline_enabled", "int"),
        "comment_inline": ("assignsubmission_comments_enabled", "int"),
        "grade_type": ("grade[modgrade_type]", "str"),
        "remind_grading_by": ("gradingduedate", "datetime"),
        "teams_grouping": ("teamsubmissiongroupingid", "int"),
        "require_all_team_members_submit": ("requireallteammemberssubmit", "int"),
        # CLI-friendly aliases for fields that already have a canonical name above.
        # Both keys map to the same Moodle form field — pick whichever reads better.
        "submission_type_file": ("assignsubmission_file_enabled", "int"),
        "submission_type_online_text": ("assignsubmission_onlinetext_enabled", "int"),
        "max_size_bytes": ("assignsubmission_file_maxsizebytes", "int"),
        "accepted_filetypes": ("assignsubmission_file_filetypes[filetypes]", "str"),
        "anonymous_submissions": ("blindmarking", "int"),
        "hide_grader_identity": ("hidegrader", "int"),
        "cutoff_date": ("cutoffdate", "datetime"),
        "submission_attempts": ("attemptreopenmethod", "str"),
        "require_submission_statement": ("requiresubmissionstatement", "int"),
    },
    "quiz": {
        **_COMMON_SCHEMA,
        # General
        "description": ("introeditor[text]", "str"),
        # Timing
        "available_from": ("timeopen", "datetime"),
        "due_date": ("timeclose", "datetime"),
        "time_limit_mins": ("timelimit", "duration_mins"),
        "when_time_expires": ("overduehandling", "str"),  # autosubmit|graceperiod|autoabandon
        "grace_period_mins": ("graceperiod", "duration_mins"),
        # Grade
        "max_grade": ("grade", "float"),
        "grade_category": ("gradecat", "int"),
        "grade_to_pass": ("gradepass", "float"),
        "grade_method": ("grademethod", "str"),  # 1=highest 2=avg 3=first 4=last
        "attempts_allowed": ("attempts", "int"),
        "delay_1_mins": ("delay1", "duration_mins"),
        "delay_2_mins": ("delay2", "duration_mins"),
        # Layout
        "questions_per_page": ("questionsperpage", "int"),
        "navigation_method": ("navmethod", "str"),  # free|sequential
        # Question behaviour
        "shuffle_answers": ("shuffleanswers", "int"),
        "review_behaviour": ("preferredbehaviour", "str"),  # deferredfeedback|immediatefeedback|etc
        "redo_questions": ("canredoquestions", "int"),
        # Review options — during attempt
        "review_attempt_during": ("attemptduring", "int"),
        # Review options — after closing
        "review_attempt_closed": ("attemptclosed", "int"),
        "review_attempt_on_last": ("attemptonlast", "int"),
        "review_correctness_closed": ("correctnessclosed", "int"),
        "review_marks_closed": ("marksclosed", "int"),
        "review_max_marks_closed": ("maxmarksclosed", "int"),
        "review_specific_feedback_closed": ("specificfeedbackclosed", "int"),
        "review_general_feedback_closed": ("generalfeedbackclosed", "int"),
        "review_right_answer_closed": ("rightanswerclosed", "int"),
        "review_overall_feedback_closed": ("overallfeedbackclosed", "int"),
        # Appearance
        "show_user_picture": ("showuserpicture", "int"),
        "decimal_places": ("decimalpoints", "int"),
        "question_decimal_places": ("questiondecimalpoints", "int"),
        "show_blocks": ("showblocks", "int"),
        # Security / restrictions
        "password": ("quizpassword", "str"),
        "network_address": ("subnet", "str"),
        "browser_security": ("browsersecurity", "str"),
        "start_time_limit_mins": ("startlimit", "duration_mins"),
        # Safe Exam Browser
        "seb_require": ("seb_requiresafeexambrowser", "str"),
        "seb_show_download_link": ("seb_showsebdownloadlink", "int"),
        "seb_allow_quit": ("seb_allowuserquitseb", "int"),
        "seb_confirm_quit": ("seb_userconfirmquit", "int"),
        "seb_quit_password": ("seb_quitpassword", "str"),
        "seb_allow_reload": ("seb_allowreloadinexam", "int"),
        "seb_show_taskbar": ("seb_showsebtaskbar", "int"),
        "seb_show_reload_button": ("seb_showreloadbutton", "int"),
        "seb_show_time": ("seb_showtime", "int"),
        "seb_show_keyboard": ("seb_showkeyboardlayout", "int"),
        "seb_show_wifi": ("seb_showwificontrol", "int"),
        "seb_enable_audio": ("seb_enableaudiocontrol", "int"),
        "seb_mute_on_startup": ("seb_muteonstartup", "int"),
        "seb_allow_spell_check": ("seb_allowspellchecking", "int"),
        "seb_url_filtering": ("seb_activateurlfiltering", "int"),
        # Completion (quiz-specific extras beyond _COMMON_SCHEMA)
        "completion_min_attempts": ("completionminattempts", "int"),
        "completion_attempts_exhausted": ("completionattemptsexhausted", "int"),
    },
    "forum": {
        **_COMMON_SCHEMA,
        "description": ("introeditor[text]", "str"),
        "forum_type": ("type", "str"),
        "max_file_size": ("maxbytes", "int"),
        "max_attachments": ("maxattachments", "int"),
        "subscription_mode": ("forcesubscribe", "str"),  # 0=optional 1=forced 2=auto 3=disabled
        "tracking_type": ("trackingtype", "str"),
        "completion_posts": ("completionposts", "int"),
        "completion_discussions": ("completiondiscussions", "int"),
        "completion_replies": ("completionreplies", "int"),
    },
    "resource": {
        **_COMMON_SCHEMA,
        "description": ("introeditor[text]", "str"),
        "display_mode": ("display", "int"),  # 0=auto 1=embed 2=force download etc.
        "show_size": ("showsize", "int"),
        "show_type": ("showtype", "int"),
        "show_date": ("showdate", "int"),
    },
    "url": {
        **_COMMON_SCHEMA,
        "description": ("introeditor[text]", "str"),
        "external_url": ("externalurl", "str"),
        "display_mode": ("display", "int"),
    },
    "page": {
        **_COMMON_SCHEMA,
        "description": ("introeditor[text]", "str"),
        "content": ("page[text]", "str"),
        "display_mode": ("display", "int"),
    },
    "label": {
        **_COMMON_SCHEMA,
        "content": ("introeditor[text]", "str"),
    },
    "assign_default": {
        **_COMMON_SCHEMA,
        "description": ("introeditor[text]", "str"),
    },
}
_DEFAULT_SCHEMA = _SETTINGS_SCHEMA["assign_default"]

# ── Course-level settings schema (course/edit.php) ────────────────────────────
# type_hint: same as module schema — "str" | "int" | "float" | "datetime" | "tags"
_COURSE_SETTINGS_SCHEMA: dict[str, tuple[str, str]] = {
    # General
    "fullname": ("fullname", "str"),
    "shortname": ("shortname", "str"),
    "id_number": ("idnumber", "str"),
    "visible": ("visible", "int"),
    "start_date": ("startdate", "datetime_always"),
    "end_date": ("enddate", "datetime"),
    # Description
    "summary": ("summary_editor[text]", "str"),
    # Course format
    "format": ("format", "str"),  # topics|weeks|social|singleactivity
    "hidden_sections": ("hiddensections", "int"),  # 0=collapsed 1=invisible
    "course_layout": ("coursedisplay", "int"),  # 0=all on one page 1=one section per page
    # Appearance
    "force_language": ("lang", "str"),
    "announcements_count": ("newsitems", "int"),
    "show_gradebook": ("showgrades", "int"),
    "show_activity_reports": ("showreports", "int"),
    "show_activity_dates": ("showactivitydates", "int"),
    # Files and uploads
    "max_upload_size": ("maxbytes", "int"),
    # Completion tracking
    "enable_completion": ("enablecompletion", "int"),
    "show_completion_conditions": ("showcompletionconditions", "int"),
    # Groups
    "group_mode": ("groupmode", "int"),  # 0=no groups 1=separate 2=visible
    "force_group_mode": ("groupmodeforce", "int"),
    "default_grouping": ("defaultgroupingid", "int"),
    # Tags
    "tags": ("tags", "tags"),
}


def _build_module_settings(form: dict[str, str], modname: str) -> dict[str, Any]:
    """Build a curated settings dict from raw form data using the per-type schema.

    Only non-trivially-default values are included (non-zero ints, non-empty strings,
    non-empty dates, non-empty tags, non-zero durations). This keeps the YAML clean and
    lets diff() skip modules whose settings are entirely at their defaults.
    """
    schema = _SETTINGS_SCHEMA.get(modname, _DEFAULT_SCHEMA)
    result: dict[str, Any] = {}
    for key, (field, kind) in schema.items():
        if kind == "datetime":
            val = _parse_datetime(form, field)
            if val:
                result[key] = val
        elif kind == "duration_mins":
            val = _parse_duration_mins(form, field)
            if val:
                result[key] = val
        elif kind == "tags":
            tags: list[str] = []
            i = 0
            while f"{field}[{i}]" in form:
                tags.append(form[f"{field}[{i}]"])
                i += 1
            if tags:
                result[key] = tags
        elif kind == "int":
            raw = form.get(field, "0")
            try:
                val_int = int(float(raw)) if raw else 0
            except (ValueError, TypeError):
                val_int = 0
            if val_int:
                result[key] = val_int
        elif kind == "float":
            raw = form.get(field, "")
            try:
                val_float = float(raw) if raw else 0.0
            except ValueError:
                val_float = 0.0
            if val_float:
                result[key] = val_float
        else:  # str
            val = form.get(field, "")
            if val:
                result[key] = val
    return result


def _settings_to_form(modname: str, settings: dict[str, Any]) -> dict[str, str]:
    """Convert curated settings dict back to modedit.php form fields.

    Used by `content set` and UPDATE_MODULE push. Unknown keys (raw field names)
    are passed through directly so callers can bypass the schema when needed.
    """
    schema = _SETTINGS_SCHEMA.get(modname, _DEFAULT_SCHEMA)
    form_changes: dict[str, str] = {}
    for key, value in settings.items():
        if key in schema:
            field, kind = schema[key]
            if kind == "datetime":
                val_str = str(value) if value else ""
                if val_str and _DATE_RE.match(val_str):
                    form_changes.update(_datetime_to_form(val_str, field))
                else:
                    form_changes[f"{field}[enabled]"] = ""  # disable the date
            elif kind == "duration_mins":
                form_changes.update(_duration_mins_to_form(int(value or 0), field))
            elif kind == "tags":
                tag_list = value if isinstance(value, list) else ([value] if value else [])
                for i, tag in enumerate(tag_list):
                    form_changes[f"{field}[{i}]"] = str(tag)
            else:
                form_changes[field] = str(value) if value is not None else ""
        else:
            # Raw form field name — pass through; update_module handles date expansion
            form_changes[key] = str(value) if value is not None else ""
    return form_changes


def _course_settings_to_form(settings: dict[str, Any]) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
    """Convert curated course settings dict back to course/edit.php form fields."""
    form_changes: dict[str, str] = {}
    for key, value in settings.items():
        if key in _COURSE_SETTINGS_SCHEMA:
            field, kind = _COURSE_SETTINGS_SCHEMA[key]
            if kind in ("datetime", "datetime_always"):
                val_str = str(value) if value else ""
                if val_str and _DATE_RE.match(val_str):
                    form_changes.update(_datetime_to_form(val_str, field))
                else:
                    form_changes[f"{field}[enabled]"] = ""
            elif kind == "tags":
                tag_list = value if isinstance(value, list) else ([value] if value else [])
                for i, tag in enumerate(tag_list):
                    form_changes[f"{field}[{i}]"] = str(tag)
            else:
                form_changes[field] = str(value) if value is not None else ""
        else:
            form_changes[key] = str(value) if value is not None else ""
    return form_changes


def _build_module_settings_dynamic(form: dict[str, str]) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
    """Extract ALL form fields for `content settings` display (not used in YAML).

    Date groups are collapsed; system/routing fields are excluded.
    """
    _SYSTEM = frozenset({
        "sesskey", "update", "return", "course", "coursemodule", "instance",
        "section", "module", "modulename", "submitbutton", "submitbutton2", "cancel",
        "timemodified", "beforemod", "sr", "add", "showonly",
    })
    _SYS_PFX = ("_qf__", "mform_isexpanded_")

    date_prefixes: set[str] = set()
    for key in form:
        m = re.match(r'^(.+)\[enabled\]$', key)
        if m and f"{m.group(1)}[day]" in form:
            date_prefixes.add(m.group(1))

    date_sub_keys: set[str] = {
        f"{p}[{part}]"
        for p in date_prefixes
        for part in ("enabled", "day", "month", "year", "hour", "minute")
    }

    result: dict[str, Any] = {}
    for prefix in sorted(date_prefixes):
        result[prefix] = _parse_datetime(form, prefix)

    for key, value in form.items():
        if key in date_sub_keys:
            continue
        if key in _SYSTEM:
            continue
        if any(key.startswith(p) for p in _SYS_PFX):
            continue
        if key.endswith("[itemid]"):
            continue
        if re.search(r'\[(format|trust|rescalegrades)\]$', key):
            continue
        result[key] = value

    return result


def _json_int(v: JSON | None, default: int = 0) -> int:
    """Coerce a JSON value to int, defaulting when impossible. Type-safe: never
    raises and never widens to Any."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return default
    return default


def _parse_modedit_form(soup: BeautifulSoup, origin: str) -> dict[str, str]:
    """Extract all form fields (hidden + visible) from a modedit.php page soup.

    `origin` is a human-readable hint used only in error messages.
    """
    forms = soup.find_all("form")
    if not forms:
        raise RuntimeError(
            f"modedit.php returned no form for {origin}. "
            f"Module type may be unavailable in this course."
        )
    form = max(forms, key=lambda f: len(f.find_all(["input", "select", "textarea"])))

    data: dict[str, str] = {}
    for el in form.find_all(["input", "select", "textarea"]):
        name = _attr(el, "name")
        if not name:
            continue
        tag = el.name
        input_type = _attr(el, "type", "text").lower()
        if input_type == "submit":
            continue
        if tag == "select":
            if el.get("multiple") is not None:
                selected_opts = el.find_all("option", selected=True)
                base = name.rstrip("[]")
                if selected_opts:
                    for i, opt in enumerate(selected_opts):
                        data[f"{base}[{i}]"] = _attr(opt, "value")
            else:
                selected = el.find("option", selected=True)
                data[name] = _attr(selected, "value") if selected else ""
        elif tag == "textarea":
            data[name] = el.get_text()
        elif input_type == "checkbox":
            if el.get("checked") is not None:
                data[name] = _attr(el, "value", "1")
        elif input_type == "radio":
            if el.get("checked") is not None:
                data[name] = _attr(el, "value")
        else:
            data[name] = _attr(el, "value")

    data["submitbutton2"] = "Save and return to course"
    return data


class MoodleAPI(MoodleClientBase):

    def _get_soup(self, url: str, params: dict[str, str | int] | None = None, context: str = "") -> BeautifulSoup:
        """GET a Moodle page, check for session expiry, and return a parsed BeautifulSoup.

        Raises RuntimeError with a clear message if the response redirects to login.
        context: short description of what was being loaded (used in the error message).
        """
        resp = self._session.get(url, params=params or {})
        if "login" in resp.url:
            detail = f" while loading {context}" if context else ""
            raise RuntimeError(
                f"Session expired{detail}.\n{_SESSION_EXPIRED}"
            )
        return BeautifulSoup(resp.text, "html.parser")

    # ── Courses ───────────────────────────────────────────────────────────────

    def get_course_form(self, course_id: CourseId) -> dict[str, str]:
        """Scrape the course/edit.php form and return all field values."""
        resp = self._session.get(
            f"{self.base_url}/course/edit.php",
            params={"id": int(course_id)},
        )
        if "login" in resp.url:
            raise RuntimeError(f"Session expired while loading course settings.\n{_SESSION_EXPIRED}")
        soup = BeautifulSoup(resp.text, "html.parser")
        form = max(
            soup.find_all("form"),
            key=lambda f: len(f.find_all(["input", "select", "textarea"])),
        )
        data: dict[str, str] = {}
        for el in form.find_all(["input", "select", "textarea"]):
            name = _attr(el, "name")
            if not name:
                continue
            tag = el.name
            input_type = _attr(el, "type", "text").lower()
            if input_type == "submit":
                # Drop all submit buttons; we re-add the one we want below.
                continue
            if tag == "select":
                if el.get("multiple") is not None:
                    base = name.rstrip("[]")
                    selected_opts = el.find_all("option", selected=True)
                    if selected_opts:
                        for i, opt in enumerate(selected_opts):
                            data[f"{base}[{i}]"] = _attr(opt, "value")
                    # For empty multiselects, don't post `base[] = ""` — PHP would
                    # parse it as `[""]` and Moodle's get_in_or_equal() chokes on
                    # the resulting array. The hidden sentinel (e.g. `tags =
                    # _qf__force_multiselect_submission`) already covers the
                    # "empty selection submitted" case.
                else:
                    selected = el.find("option", selected=True)
                    data[name] = _attr(selected, "value") if selected else ""
            elif tag == "textarea":
                data[name] = el.get_text()
            elif input_type == "checkbox":
                if el.get("checked") is not None:
                    data[name] = _attr(el, "value", "1")
            elif input_type == "radio":
                if el.get("checked") is not None:
                    data[name] = _attr(el, "value")
            else:
                data[name] = _attr(el, "value")
        data["saveanddisplay"] = "Save and display"
        return data

    def update_course(self, course_id: CourseId, changes: dict[str, str]) -> None:
        """Apply changes to course settings via course/edit.php."""
        get_url = f"{self.base_url}/course/edit.php"
        form_data = self.get_course_form(course_id)
        for key, value in changes.items():
            val = str(value) if value else ""
            if val and _DATE_RE.match(val):
                form_data.update(_datetime_to_form(val, key))
            elif not val and f"{key}[enabled]" in form_data:
                form_data[f"{key}[enabled]"] = ""
            else:
                form_data[key] = val
        resp = self._post_form(
            f"{self.base_url}/course/edit.php",
            form_data,
            referer=get_url,
        )
        if resp.status_code == 404:
            raise RuntimeError(f"course/edit.php POST returned 404 for course {course_id}")
        if "edit.php" in resp.url and resp.status_code == 200:
            import tempfile
            soup = BeautifulSoup(resp.text, "html.parser")
            msg = ""
            for candidate in [
                *soup.find_all(id=re.compile(r"^id_error_")),
                *soup.find_all(class_="formerror"),
                *soup.find_all(class_="alert-danger"),
                *soup.find_all(class_="error"),
            ]:
                text = candidate.get_text(separator=" ", strip=True)
                if text:
                    msg = text
                    break
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html", prefix=f"moodlectl_err_course{course_id}_")
            tmp.write(resp.text.encode("utf-8", errors="replace"))
            tmp.close()
            raise RuntimeError(
                f"Moodle rejected course settings for {course_id}: {msg or 'unknown error'}\n"
                f"Full response saved to: {tmp.name}"
            )

    def get_courses(self, classification: str = "all", sort: str = "fullname") -> list[Course]:
        """Return the user's enrolled courses.

        Tries the timeline-classification webservice first (fast, single round-trip).
        Falls back to scraping `/my/courses.php` when the service rejects the call —
        older Moodles (<3.11) trip on optional params, and some sites disable the
        web service entirely.
        """
        try:
            raw = self.ajax("core_course_get_enrolled_courses_by_timeline_classification", {
                "offset": 0,
                "limit": 0,
                "classification": classification,
                "sort": sort,
                "requiredfields": ["id", "fullname", "shortname", "visible", "enddate"],
            })
            data = cast(dict[str, list[Course]], raw)
            return data["courses"]
        except RuntimeError:
            return self._scrape_my_courses()

    def _scrape_my_courses(self) -> list[Course]:
        """Scrape an enrolled-course list from a server-rendered Moodle page.

        Modern Moodle 4.x dashboards are JS-rendered and contain no course data
        in the initial HTML, so we use the calendar page's course filter — its
        `<select name="course">` is server-rendered with one option per course
        the user can see. The "All courses" sentinel (value=1) is dropped.
        """
        try:
            soup = self._get_soup(
                f"{self.base_url}/calendar/view.php",
                params={"view": "month"},
                context="enrolled courses (calendar fallback)",
            )
        except Exception:
            return []

        sel = soup.find("select", {"name": "course"})
        if sel is None:
            sel = soup.find("select", id=re.compile("course"))
        if sel is None:
            return []

        out: list[Course] = []
        for opt in sel.find_all("option"):
            raw_v = str(opt.get("value") or "")
            if not raw_v.isdigit():
                continue
            cid = int(raw_v)
            if cid <= 1:  # 0 = none, 1 = "All courses" / site front page
                continue
            name = opt.get_text(" ", strip=True)
            if not name:
                continue
            out.append({
                "id": CourseId(cid),
                "fullname": name,
                "shortname": name,
                "visible": 1,
                "enddate": 0,
            })
        return out

    # ── Participants ──────────────────────────────────────────────────────────

    def get_course_participants(self, course_id: CourseId) -> list[Participant]:
        """Scrape the participants page for a course.

        Table columns: [checkbox, fullname, email, roles, groups, lastaccess, status]
        """
        soup = self._get_soup(
            f"{self.base_url}/user/index.php",
            params={"id": course_id, "perpage": 5000},
            context=f"participants for course {course_id}",
        )

        table = soup.find("table", {"id": "participants"})
        if not table:
            return []

        tbody = table.find("tbody")
        if not tbody:
            return []

        participants: list[Participant] = []
        for row in tbody.find_all("tr"):
            cols = row.find_all(["td", "th"])
            if len(cols) < 3:
                continue

            # User ID from checkbox input id e.g. id="user1557"
            checkbox = cols[0].find("input")
            user_id: UserId | None = None
            if checkbox:
                cid_attr = _attr(checkbox, "id")
                if cid_attr.startswith("user"):
                    try:
                        user_id = UserId(int(cid_attr.replace("user", "")))
                    except ValueError:
                        pass

            # Fullname: strip the avatar initials (first 2 chars like "AA")
            name_link = cols[1].find("a")
            if name_link:
                fullname = name_link.get_text(strip=True)[2:]
            else:
                fullname = cols[1].get_text(strip=True)

            email = cols[2].get_text(strip=True) if len(cols) > 2 else ""
            roles = cols[3].get_text(strip=True) if len(cols) > 3 else ""
            lastaccess = cols[5].get_text(strip=True) if len(cols) > 5 else ""
            status = cols[6].get_text(strip=True) if len(cols) > 6 else ""

            if not fullname or user_id is None:
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

    def get_grade_report(self, course_id: CourseId) -> GradeReport:
        """Scrape the grader report (teacher view) for a course, all pages.

        Returns {"columns": [...], "rows": [{"id", "fullname", "email", col: grade, ...}]}
        """
        columns: list[str] = []
        column_cmids: dict[str, int | None] = {}
        all_student_rows: list[dict[str, str | int]] = []
        page = 0

        while True:
            soup = self._get_soup(
                f"{self.base_url}/grade/report/grader/index.php",
                params={"id": course_id, "page": page},
                context="grade report",
            )

            table = soup.find("table", {"id": "user-grades"})
            if not table:
                break

            all_rows = table.find_all("tr")

            # Parse column headers once (from first page only)
            if not columns:
                heading_row = next(
                    (r for r in all_rows if "heading" in _classes(r)), None
                )
                if heading_row:
                    for th in heading_row.find_all(["th", "td"]):
                        name = None
                        cmid: int | None = None
                        for a in th.find_all("a"):
                            title = _attr(a, "title")
                            if title.startswith("Link to"):
                                name = re.sub(r"^Link to \S+ activity ", "", title).strip()
                                href = _attr(a, "href")
                                m = re.search(r"[?&]id=(\d+)", href)
                                if m:
                                    cmid = int(m.group(1))
                                break
                        if not name:
                            raw = th.get_text(separator=" ", strip=True)
                            name = re.sub(
                                r"\s*(Cell actions|Ascending|Descending|Collapse|Expand column)\b.*",
                                "", raw, flags=re.DOTALL,
                            ).strip()
                        col_name = name or f"col{len(columns)}"
                        columns.append(col_name)
                        column_cmids[col_name] = cmid

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
                grade_cells = [c for c in cols[2:] if "gradecell" in " ".join(_classes(c))]
                for i, cell in enumerate(grade_cells):
                    col_name = columns[i + 2] if i + 2 < len(columns) else f"item_{i}"
                    raw_val = cell.get_text(strip=True)
                    val = re.sub(r"Cell actions.*|Grade analysis.*", "", raw_val).strip()
                    grades[col_name] = val or "-"

                total_col = columns[-1] if columns else "Course total"
                total_cell = next(
                    (c for c in reversed(cols) if "course" in " ".join(_classes(c))), None
                )
                total = re.sub(r"\s+", "", total_cell.get_text(strip=True)) if total_cell else "-"

                row: dict[str, str | int] = {
                    "id": _int_attr(tr, "data-uid"),
                    "fullname": fullname,
                    "email": email,
                    **grades,
                }
                row[total_col] = total
                all_student_rows.append(row)

            # Stop when a page returns fewer than a full page of rows (20)
            if len(page_rows) < 20:
                break
            page += 1

        return GradeReport(columns=columns, rows=all_student_rows, column_cmids=column_cmids)

    # ── Assignments ───────────────────────────────────────────────────────────

    def get_course_assignments(self, course_id: CourseId) -> list[AssignmentMeta]:
        """Scrape the assignment index page for a course.

        Returns list of:
          {cmid, name, due_text, submitted_count}
        """
        soup = self._get_soup(
            f"{self.base_url}/mod/assign/index.php",
            params={"id": course_id},
            context=f"assignments for course {course_id}",
        )

        table = soup.find("table", class_="generaltable")
        if not table:
            return []

        tbody = table.find("tbody")
        if not tbody:
            return []

        assignments: list[AssignmentMeta] = []
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
            href = _attr(link, "href")
            m = re.search(r"[?&]id=(\d+)", href)
            if not m:
                continue
            cmid = Cmid(int(m.group(1)))

            due_text = cols[2].get_text(strip=True) if len(cols) > 2 else ""

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

    def get_assignment_brief_files(self, cmid: Cmid) -> list[FileRef]:
        """Scrape the assignment view page for instructor-attached brief files.

        Returns list of {filename, url} for files attached to the assignment description.
        """
        soup = self._get_soup(
            f"{self.base_url}/mod/assign/view.php",
            params={"id": cmid},
            context=f"assignment {cmid}",
        )

        files: list[FileRef] = []
        for a in soup.find_all("a", href=True):
            href = _attr(a, "href")
            if "pluginfile.php" in href and "mod_assign/introattachment" in href:
                filename = a.get_text(strip=True)
                if filename:
                    files.append({"filename": filename, "url": href})
        return files

    def get_assignment_submissions(self, cmid: Cmid) -> list[Submission]:
        """Scrape the grading page for an assignment.

        Returns list of:
          {user_id, fullname, email, status, grading_status, files: [{filename, url}]}

        Only entries with at least one uploaded file are included.
        """
        soup = self._get_soup(
            f"{self.base_url}/mod/assign/view.php",
            params={"id": cmid, "action": "grading", "perpage": 1000},
            context=f"submissions for assignment {cmid}",
        )

        table = soup.find("table", class_="generaltable")
        if not table:
            return []

        tbody = table.find("tbody")
        if not tbody:
            return []

        results: list[Submission] = []
        for row in tbody.find_all("tr"):
            cols = row.find_all(["td", "th"])
            if len(cols) < 9:
                continue

            # col 2: fullname + link with user_id
            name_cell = cols[2]
            fullname = name_cell.get_text(strip=True)
            user_id: UserId | None = None
            profile_link = name_cell.find("a")
            if profile_link:
                m = re.search(r"[?&]id=(\d+)", _attr(profile_link, "href"))
                if m:
                    user_id = UserId(int(m.group(1)))

            if not fullname or user_id is None:
                continue

            email = cols[3].get_text(strip=True)
            status_text = cols[4].get_text(strip=True)
            grading_status = cols[5].get_text(strip=True) if len(cols) > 5 else ""

            # col 8: file submissions
            files: list[FileRef] = []
            for a in cols[8].find_all("a"):
                href = _attr(a, "href")
                if "pluginfile.php" in href:
                    files.append({"filename": a.get_text(strip=True), "url": href})

            if not files:
                continue

            results.append({
                "user_id": user_id,
                "fullname": fullname,
                "email": email,
                "status": status_text,
                "grading_status": grading_status,
                "files": files,
            })

        return results

    def get_assignment_internal_id(self, cmid: Cmid) -> tuple[int, int]:
        """Return (internal_assignment_id, context_id) for a given cmid.

        These IDs are needed for grade submission and differ from the cmid.
        Scraped from the grader page's data attributes.
        """
        soup = self._get_soup(
            f"{self.base_url}/mod/assign/view.php",
            params={"id": cmid, "action": "grader"},
            context=f"grader page for assignment {cmid}",
        )

        grade_div = soup.find(attrs={"data-region": "grade"})
        if not grade_div:
            raise RuntimeError(f"Could not find grade panel for cmid={cmid}")
        assignment_id = _int_attr(grade_div, "data-assignmentid")
        context_id = _int_attr(grade_div, "data-contextid")
        return assignment_id, context_id

    def get_grade_form_fragment(self, context_id: int, user_id: UserId) -> FormFields:
        """Load the grading form fragment for a student.

        Returns the raw form field dict (as parsed from the fragment HTML).
        The itemid for the feedback editor changes per request — always fetch
        a fresh fragment immediately before submitting.
        """
        raw = self.ajax("core_get_fragment", {
            "component": "mod_assign",
            "callback": "gradingpanel",
            "contextid": context_id,
            "args": [
                {"name": "userid", "value": str(user_id)},
                {"name": "attemptnumber", "value": "-1"},
                {"name": "jsonformdata", "value": ""},
            ],
        })
        result = cast(dict[str, str], raw)
        html = result.get("html", "")
        soup = BeautifulSoup(html, "html.parser")

        fields: FormFields = {}
        for el in soup.find_all(["input", "textarea", "select"]):
            name = _attr(el, "name")
            if not name:
                continue
            if el.name == "textarea":
                fields[name] = el.get_text()
            elif el.name == "select":
                selected = el.find("option", selected=True)
                fields[name] = _attr(selected, "value") if selected else ""
            else:
                fields[name] = _attr(el, "value")

        # Parse grade max from label text e.g. "Grade out of 10"
        label = soup.find("label", {"for": "id_grade"})
        grade_max: str = ""
        if label:
            m = re.search(r"out of\s+([\d.]+)", label.get_text(), re.IGNORECASE)
            if m:
                grade_max = m.group(1)

        fields["__grade_max__"] = grade_max
        return fields

    def submit_grade_for_user(
            self,
            cmid: Cmid,
            user_id: UserId,
            grade: float,
            feedback: str = "",
            notify_student: bool = False,
    ) -> float:
        """High-level grade submission: resolves IDs, fetches fresh form, submits.

        Returns the grade_max so the caller can display it.
        Raises RuntimeError if the grade could not be saved.

        Steps:
          1. Scrape grader page → (assignment_id, context_id) — different from cmid
          2. Fetch fresh form fragment — itemid changes each request, must not be cached
          3. Submit via mod_assign_submit_grading_form — empty list = success
        """
        # 1. Resolve internal IDs from cmid
        assignment_id, context_id = self.get_assignment_internal_id(cmid)

        # 2. Load fresh form fragment (itemid is one-time use)
        fields = self.get_grade_form_fragment(context_id, user_id)
        grade_max = float(fields.pop("__grade_max__") or 0)

        # 3. Override grade, feedback, and notification preference
        fields["grade"] = str(grade)
        fields["assignfeedbackcomments_editor[text]"] = feedback
        fields["sendstudentnotifications"] = "1" if notify_student else "0"

        # 4. Submit
        raw = self.ajax("mod_assign_submit_grading_form", {
            "assignmentid": assignment_id,
            "userid": user_id,
            "jsonformdata": json.dumps(urlencode(fields)),
        })
        result = cast(list[dict[str, str]], raw)

        # Empty list = success; non-empty list = validation errors
        if result:
            errors = "; ".join(e.get("message", str(e)) for e in result)
            raise RuntimeError(f"Grade submission failed: {errors}")

        return grade_max

    # ── Question bank: lookup + quiz wiring ───────────────────────────────────

    def list_question_categories(self, course_id: CourseId) -> list[dict[str, Any]]:
        """Return every question category visible from the course, with counts.

        Each entry: {"id", "context_id", "name", "count", "depth"}.
        `depth` is the nesting level (1 = top-level under the context root).
        """
        resp = self._session.get(
            f"{self.base_url}/question/bank/managecategories/category.php",
            params={"courseid": int(course_id)},
        )
        resp.raise_for_status()
        if "/login/index.php" in resp.url:
            raise RuntimeError("Session expired. Run `moodlectl auth login`.")

        soup = BeautifulSoup(resp.text, "html.parser")
        out: list[dict[str, Any]] = []
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "")
            if "edit.php" not in href:
                continue
            m = re.search(r"cat=(\d+)(?:%2C|,)(\d+)", href)
            if not m:
                continue
            text = a.get_text(strip=True)
            count_match = re.search(r"\((\d+)\)\s*$", text)
            count = int(count_match.group(1)) if count_match else 0
            name = re.sub(r"\s*\(\d+\)\s*$", "", text).strip()

            # Nesting depth = number of <ul> ancestors of the enclosing <li>.
            depth = 0
            node = a.find_parent("li")
            while node is not None:
                node = node.find_parent("ul")
                if node is None:
                    break
                depth += 1

            out.append({
                "id": int(m.group(1)),
                "context_id": int(m.group(2)),
                "name": name,
                "count": count,
                "depth": depth,
            })
        return out

    def list_questions_in_category(
            self, course_id: CourseId, category_id: int, context_id: int,
    ) -> list[dict[str, Any]]:
        """Return one entry per question in the category.

        Each entry: {"id", "name", "type", "status", "usage", "last_used"}.
        """
        resp = self._session.get(
            f"{self.base_url}/question/edit.php",
            params={
                "courseid": int(course_id),
                "cat": f"{int(category_id)},{int(context_id)}",
                "qperpage": 1000,
            },
        )
        resp.raise_for_status()
        if "/login/index.php" in resp.url:
            raise RuntimeError("Session expired.")

        out: list[dict[str, Any]] = []
        seen: set[int] = set()
        for tr_match in re.finditer(
            r'<tr[^>]*class="r[01]"[^>]*>(.*?)</tr>', resp.text, re.DOTALL,
        ):
            row = tr_match.group(0)
            qid_match = re.search(r'data-questionid="(\d+)"', row)
            if not qid_match:
                continue
            qid = int(qid_match.group(1))
            if qid in seen:
                continue
            seen.add(qid)

            entry: dict[str, Any] = {
                "id": qid, "name": "", "type": "",
                "status": "", "usage": 0, "last_used": "",
            }
            for td in re.finditer(
                r'<td[^>]*data-columnid="([^"]+)"[^>]*>(.*?)</td>',
                row, re.DOTALL,
            ):
                col = td.group(1)
                body = td.group(2)
                if "question_type_column" in col:
                    img = re.search(r'<img[^>]*alt="([^"]+)"', body)
                    if img:
                        entry["type"] = img.group(1)
                else:
                    import html as _html
                    flat = re.sub(r"<[^>]+>", " ", body)
                    flat = _html.unescape(re.sub(r"\s+", " ", flat).strip())
                    if "question_name" in col:
                        entry["name"] = flat
                    elif "question_status_column" in col:
                        # The cell renders both "Ready" and "Draft" — first word is the active value.
                        entry["status"] = flat.split(" ")[0] if flat else ""
                    elif "question_usage_column" in col:
                        entry["usage"] = int(flat) if flat.isdigit() else 0
                    elif "question_last_used_column" in col:
                        entry["last_used"] = flat
            out.append(entry)
        return out

    def find_question_category(self, course_id: CourseId, name: str) -> tuple[int, int]:
        """Return (categoryid, contextid) for the question category with the given name.

        Scrapes /question/bank/managecategories/category.php?courseid=X.
        Each category is rendered as an <a href="...&cat=<catid>,<ctxid>">Name (N)</a>.
        Match is case-sensitive, on the trimmed text with the trailing "(count)"
        stripped.
        """
        resp = self._session.get(
            f"{self.base_url}/question/bank/managecategories/category.php",
            params={"courseid": int(course_id)},
        )
        resp.raise_for_status()
        if "/login/index.php" in resp.url:
            raise RuntimeError("Session expired. Run `moodlectl auth login`.")
        target = name.strip()
        for m in re.finditer(
            r'href="[^"]*cat=(\d+)(?:%2C|,)(\d+)[^"]*"[^>]*>\s*([^<]+?)\s*</a>',
            resp.text,
        ):
            cat_id, ctx_id, text = m.group(1), m.group(2), m.group(3)
            clean = re.sub(r"\s*\(\d+\)\s*$", "", text).strip()
            if clean == target:
                return int(cat_id), int(ctx_id)
        raise RuntimeError(
            f"Question category {name!r} not found in course {course_id}'s question bank."
        )

    def delete_question_category(
            self, course_id: CourseId, category_id: int, context_id: int,
    ) -> dict[str, int]:
        """Delete a question-bank category along with every question in it.

        Two-step flow that mirrors the in-product UI:

          1. Bulk-delete every question in the category via
             /question/edit.php (deleteall=1 + per-question checkboxes).
          2. Delete the now-empty category via the manage-categories page.

        Returns {"questions_deleted": N, "category_deleted": 0|1}.
        """
        cat_param = f"{int(category_id)},{int(context_id)}"
        bank_url = f"{self.base_url}/question/edit.php"

        list_resp = self._session.get(
            bank_url, params={"courseid": int(course_id), "cat": cat_param},
        )
        list_resp.raise_for_status()
        qids = sorted({
            int(m.group(1))
            for m in re.finditer(r'data-questionid="(\d+)"', list_resp.text)
        })

        if qids:
            # Two-step delete via /question/bank/deletequestion/delete.php:
            # GET produces a confirmation form carrying a one-time `confirm`
            # token; POST that form back to commit.
            delete_url = f"{self.base_url}/question/bank/deletequestion/delete.php"
            params: dict[str, str] = {
                "deleteselected": ",".join(str(q) for q in qids),
                "sesskey": self.sesskey,
                "courseid": str(int(course_id)),
                "returnurl": f"/question/edit.php?courseid={int(course_id)}&cat={cat_param}",
                "deleteall": "1",
            }
            for q in qids:
                params[f"q{q}"] = "1"
            stage1 = self._session.get(delete_url, params=params)
            stage1.raise_for_status()

            confirm_soup = BeautifulSoup(stage1.text, "html.parser")
            confirm_form = next(
                (f for f in confirm_soup.find_all("form")
                 if "deletequestion/delete.php" in (f.get("action") or "")),
                None,
            )
            if confirm_form is not None:
                confirm_data: dict[str, str] = {}
                for inp in confirm_form.find_all("input"):
                    n = str(inp.get("name") or "")
                    if not n:
                        continue
                    typ = str(inp.get("type") or "").lower()
                    if typ in ("submit", "button", "reset"):
                        continue
                    confirm_data[n] = str(inp.get("value") or "")
                self._session.post(
                    delete_url,
                    data=confirm_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    allow_redirects=True,
                )

        # Empty category → simple GET deletes it; if not empty, Moodle would
        # show the move-questions form, which we ignore.
        cat_url = f"{self.base_url}/question/bank/managecategories/category.php"
        self._session.get(cat_url, params={
            "courseid": int(course_id),
            "delete": int(category_id),
            "sesskey": self.sesskey,
            "confirm": 1,
        })

        # Verify the category is gone.
        check = self._session.get(cat_url, params={"courseid": int(course_id)})
        category_deleted = f"cat={int(category_id)}" not in check.text

        return {
            "questions_deleted": len(qids),
            "category_deleted": int(category_deleted),
        }

    def get_quiz_attempts(self, cmid: Cmid) -> list[dict[str, str]]:
        """Scrape the quiz overview report at /mod/quiz/report.php for one quiz.

        The report page renders only after the preferences form is POSTed back
        with its current values, so we GET → re-POST → parse the #attempts
        table. Returns one dict per attempt row with these keys:

            attempt_id, fullname, email, state, started, completed, duration,
            grade, max_grade, user_id (optional, parsed from review.php link
            when present).

        Empty list if there are no attempts (table absent on first render).
        """
        report_url = f"{self.base_url}/mod/quiz/report.php"
        params = {"id": int(cmid), "mode": "overview"}

        resp = self._session.get(report_url, params=params)
        if "login" in resp.url:
            raise RuntimeError(f"Session expired loading quiz report.\n{_SESSION_EXPIRED}")
        if resp.status_code == 404:
            raise RuntimeError(
                f"Quiz report 404 for cmid={cmid}. Likely you lack 'view all attempts' "
                f"permission on this quiz's course."
            )
        soup = BeautifulSoup(resp.text, "html.parser")
        prefs_form = soup.find("form")
        if not prefs_form:
            return []
        form_data: dict[str, str] = {}
        for inp in prefs_form.find_all(["input", "select", "textarea"]):
            n = str(inp.get("name") or "")
            if n:
                form_data[n] = str(inp.get("value", "") or "")

        resp2 = self._session.post(
            f"{report_url}?id={int(cmid)}&mode=overview",
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        soup2 = BeautifulSoup(resp2.text, "html.parser")
        table = soup2.find("table", id="attempts")
        if not table:
            return []

        # Parse "Grade/10.00" → max_grade "10.00"
        max_grade = ""
        for th in table.find_all("th"):
            txt = th.get_text(" ", strip=True)
            m = re.match(r"^Grade\s*/\s*(\S+)$", txt)
            if m:
                max_grade = m.group(1)
                break

        # Find header positions for the columns we want
        header_cells = []
        thead = table.find("thead")
        if thead:
            header_cells = thead.find_all("th")
        if not header_cells:
            first_row = table.find("tr")
            header_cells = first_row.find_all("th") if first_row else []
        col_idx: dict[str, int] = {}
        for i, th in enumerate(header_cells):
            txt = th.get_text(" ", strip=True).lower()
            if txt.startswith("first name") or txt == "name":
                col_idx["name"] = i
            elif txt.startswith("email"):
                col_idx["email"] = i
            elif txt == "status":
                col_idx["state"] = i
            elif txt == "started":
                col_idx["started"] = i
            elif txt == "completed":
                col_idx["completed"] = i
            elif txt == "duration":
                col_idx["duration"] = i
            elif txt.startswith("grade/"):
                col_idx["grade"] = i

        out: list[dict[str, str]] = []
        body = table.find("tbody") or table
        for tr in body.find_all("tr"):
            tds = tr.find_all("td")
            if not tds or len(tds) < 4:
                continue
            tr_classes = tr.get("class") or []
            if "emptyrow" in tr_classes:
                continue
            def cell(key: str) -> str:
                idx = col_idx.get(key)
                if idx is None or idx >= len(tds):
                    return ""
                return tds[idx].get_text(" ", strip=True)

            attempt_id = ""
            user_id = ""
            for a in tr.find_all("a", href=True):
                href = str(a.get("href") or "")
                m = re.search(r"review\.php\?attempt=(\d+)", href)
                if m and not attempt_id:
                    attempt_id = m.group(1)
                m = re.search(r"user/view\.php\?id=(\d+)", href)
                if m and not user_id:
                    user_id = m.group(1)

            # Strip "Review attempt" trailing text from name cell
            name_text = cell("name")
            name_text = re.sub(r"\s*Review attempt\s*$", "", name_text).strip()
            # Skip footer rows ("Overall average" etc.) and any row without a real student
            if not name_text or name_text.lower() in ("overall average", "overall mean"):
                continue

            out.append({
                "attempt_id": attempt_id,
                "user_id": user_id,
                "fullname": name_text,
                "email": cell("email"),
                "state": cell("state"),
                "started": cell("started"),
                "completed": cell("completed"),
                "duration": cell("duration"),
                "grade": cell("grade"),
                "max_grade": max_grade,
            })
        return out

    def add_random_questions_to_quiz(
            self, quiz_cmid: Cmid, category_id: int, context_id: int, count: int,
            include_subcategories: bool = False,
    ) -> None:
        """Add `count` random questions to a quiz, drawn from one bank category.

        Wraps Moodle's `mod_quiz_add_random_questions` webservice. Builds the
        `filtercondition` JSON the same way the in-product modal does — that's
        the only signature this webservice accepts in Moodle 4.x.
        """
        filter_condition = json.dumps({
            "qpage": 0,
            "cat": f"{category_id},{context_id}",
            "qperpage": 20,
            "tabname": "questions",
            "filter": {
                "category": {
                    "jointype": 1,
                    "values": [str(category_id)],
                    "filteroptions": {"includesubcategories": bool(include_subcategories)},
                    "name": "qbank_managecategories\\category_condition",
                },
            },
            "jointype": 2,
        })
        self.ajax("mod_quiz_add_random_questions", {
            "cmid": int(quiz_cmid),
            "addonpage": 0,
            "randomcount": int(count),
            "filtercondition": filter_condition,
            "newcategory": "",
            "parentcategory": "",
        })

    # ── Question bank import ──────────────────────────────────────────────────

    def import_question_bank(self, course_id: CourseId, file_path: object) -> dict[str, Any]:
        """Import a Moodle XML question bank file into a course.

        Scrapes the import form for sesskey + draft itemid, uploads the file
        into the draft area, then POSTs the form with format=xml,
        catfromfile/contextfromfile checked (so $category lines from the XML
        are honoured), and stoponerror=1.

        Returns:
            {'imported': int, 'errors': [...], 'warnings': [...], 'response_url': str}
        """
        from pathlib import Path

        path = Path(str(file_path))
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        form_url = f"{self.base_url}/question/bank/importquestions/import.php"
        resp = self._session.get(form_url, params={"courseid": int(course_id)})
        resp.raise_for_status()
        if "/login/index.php" in resp.url:
            raise RuntimeError("Session expired. Run `moodlectl auth login`.")

        soup = BeautifulSoup(resp.text, "html.parser")
        form = next(
            (f for f in soup.find_all("form")
             if "importquestions/import.php" in (f.get("action") or "")),
            None,
        )
        if not form:
            raise RuntimeError(
                "Question import form not found. The user may lack import permission "
                f"on course {course_id}."
            )

        itemid_input = form.find("input", attrs={"name": "newfile"})
        if not itemid_input or not itemid_input.get("value"):
            raise RuntimeError("Could not find draft itemid (newfile) on the import form.")
        draft_itemid = str(itemid_input.get("value", ""))

        # Push the XML into the draft area attached to this form.
        self._upload_to_draft(soup, draft_itemid, str(path))

        # Build the POST payload from the form's existing fields.
        data: dict[str, str] = {}
        for inp in form.find_all("input"):
            name = str(inp.get("name") or "")
            if not name:
                continue
            typ = str(inp.get("type") or "").lower()
            if typ in ("submit", "button", "reset", "file"):
                continue
            if typ == "radio":
                continue
            data[name] = str(inp.get("value") or "")
        for sel in form.find_all("select"):
            name = str(sel.get("name") or "")
            if not name:
                continue
            chosen = sel.find("option", selected=True) or sel.find("option")
            if chosen is not None:
                data[name] = str(chosen.get("value") or "")

        # Force the values we care about.
        data["format"] = "xml"
        data["catfromfile"] = "1"
        data["contextfromfile"] = "1"
        data["stoponerror"] = "1"
        data["newfile"] = str(draft_itemid)
        data["submitbutton"] = "Import"

        # Moodle's import.php needs courseid in the query string even for POST;
        # without it the route returns 404.
        # The shared session sets Content-Type: application/json by default for
        # AJAX calls — override it so MForm sees the URL-encoded body.
        post_resp = self._session.post(
            form_url, params={"courseid": int(course_id)},
            data=data, allow_redirects=True,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        post_resp.raise_for_status()
        result_html = post_resp.text
        result_soup = BeautifulSoup(result_html, "html.parser")

        errors: list[str] = []
        warnings: list[str] = []
        for div in result_soup.find_all("div"):
            cls_attr = div.get("class")
            if isinstance(cls_attr, list):
                cls = " ".join(str(c) for c in cls_attr)
            else:
                cls = str(cls_attr or "")
            text = div.get_text(" ", strip=True)
            if not text:
                continue
            if "notifyproblem" in cls or "alert-danger" in cls or "alert-error" in cls:
                errors.append(text)
            elif "notifywarning" in cls or "alert-warning" in cls:
                warnings.append(text)

        # Moodle prints a per-question status list; count "Importing question N"
        # or fall back to the summary line "Importing N questions from file".
        imported = 0
        m = re.search(r"Importing\s+(\d+)\s+questions?", result_html, re.IGNORECASE)
        if m:
            imported = int(m.group(1))
        else:
            imported = len(re.findall(r"Importing\s+question\s+\d+", result_html, re.IGNORECASE))

        return {
            "imported": imported,
            "errors": errors,
            "warnings": warnings,
            "response_url": post_resp.url,
        }

    def download_resource(self, cmid: Cmid, dest_dir: object) -> object:
        """Download the file backing a `resource` module to dest_dir.

        Returns the path written. Single-file resources configured to force
        download 303-redirect to their pluginfile.php URL; resources set to
        display inline (HTML, embedded PDF, …) render a wrapper page that
        contains the pluginfile.php URL in the body. We handle both.
        """
        import re
        from pathlib import Path
        from urllib.parse import unquote

        resp = self._session.get(
            f"{self.base_url}/mod/resource/view.php",
            params={"id": int(cmid)},
            allow_redirects=False,
        )

        file_url = ""
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location", "")
            if "pluginfile.php" in loc:
                file_url = loc
        elif resp.status_code == 200:
            # Inline-display resource: scrape the wrapper page for the file URL.
            page = self._session.get(
                f"{self.base_url}/mod/resource/view.php",
                params={"id": int(cmid)},
            )
            matches = re.findall(
                r'https?://[^\s"\'<>]+/pluginfile\.php/[^\s"\'<>?]+',
                page.text,
            )
            # Prefer mod_resource URLs and skip embed=1 duplicates by stripping query.
            seen: list[str] = []
            for m in matches:
                if "/mod_resource/" in m and m not in seen:
                    seen.append(m)
            if seen:
                file_url = seen[0]

        if not file_url:
            raise RuntimeError(
                f"Could not resolve file URL for resource cmid={cmid} "
                f"(status={resp.status_code})."
            )

        filename = unquote(file_url.split("?", 1)[0].rsplit("/", 1)[-1])
        dest = Path(str(dest_dir)) / filename
        self.download_file(file_url, dest)
        return dest

    def download_file(self, url: str, dest_path: object) -> None:
        """Download an authenticated Moodle file (pluginfile.php) to dest_path.

        Rewrites webservice/pluginfile.php → pluginfile.php for session-cookie auth.
        """
        from pathlib import Path

        # Moodle AJAX sometimes returns webservice/pluginfile.php URLs even when
        # using session auth — rewrite to the regular pluginfile.php path.
        url = url.replace("/webservice/pluginfile.php", "/pluginfile.php")

        path = Path(str(dest_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        resp = self._session.get(url, stream=True)
        resp.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)

    # ── Messages ──────────────────────────────────────────────────────────────

    def get_current_user_id(self) -> int:
        resp = self._session.get(f"{self.base_url}/my/")
        match = re.search(r'data-userid=["\'](\d+)["\']', resp.text)
        if not match:
            raise RuntimeError("Could not determine current user ID from dashboard page.")
        return int(match.group(1))

    def send_message(self, user_id: UserId, message: str) -> JSON:
        return self.ajax("core_message_send_instant_messages", {
            "messages": [{"touserid": user_id, "text": message, "textformat": 1}],
        })

    def delete_message(self, message_id: int) -> None:
        user_id = self.get_current_user_id()
        self.ajax("core_message_delete_message", {"messageid": message_id, "userid": user_id})

    # ── Forum discussions (Announcements) ─────────────────────────────────────

    def resolve_forum_instance(self, cmid: Cmid) -> int:
        """Return the forum row id (instance) for a forum-type course module.

        `cmid` identifies a course module slot; Moodle's forum AJAX endpoints
        need the forum's own instance id (separate table, separate id).

        Tries AJAX `core_course_get_course_module` first; if that webservice is
        disabled (common on locked-down Moodle installs), falls back to
        scraping the modedit form for the hidden `instance` field.
        """
        try:
            result = self.ajax("core_course_get_course_module", {"cmid": int(cmid)})
        except RuntimeError:
            form = self.get_module_form(cmid)
            raw = form.get("instance", "")
            if not raw.isdigit():
                raise RuntimeError(f"Could not scrape forum instance for cmid={cmid} from modedit form.")
            return int(raw)
        if not isinstance(result, dict):
            raise RuntimeError(f"Unexpected response for cmid={cmid}: {result!r}")
        cm = result.get("cm")
        if not isinstance(cm, dict) or "instance" not in cm:
            raise RuntimeError(f"No forum instance for cmid={cmid}: {result!r}")
        return _json_int(cm.get("instance"))

    def post_forum_discussion(
            self,
            forum_cmid: Cmid,
            subject: str,
            message: str,
            mail_now: bool = True,
            pinned: bool = False,
            subscribe: bool = True,
            message_format: int = 1,  # 0=moodle, 1=html, 2=plain, 4=markdown
            group_id: int = -1,
            attachment_paths: list[str] | None = None,
    ) -> int:
        """Post a new discussion by scraping /mod/forum/post.php (no webservices).

        Every option the UI exposes is patched into the scraped form:
        subject, message[text], message[format], discussionsubscribe, mailnow,
        pinned. `group_id` is sent via URL query like the UI does. Local file
        attachments are pushed into the form's draft area before submit.

        Returns the new discussion id (parsed from the post-redirect URL).
        """
        forum_id = self.resolve_forum_instance(forum_cmid)
        get_url = f"{self.base_url}/mod/forum/post.php"
        params: dict[str, str | int] = {"forum": forum_id}
        if group_id != -1:
            params["groupid"] = group_id

        resp_get = self._session.get(get_url, params=params)
        if "login" in resp_get.url:
            raise RuntimeError(f"Session expired while loading forum post form.\n{_SESSION_EXPIRED}")
        soup = BeautifulSoup(resp_get.text, "html.parser")
        forms = soup.find_all("form")
        if not forms:
            raise RuntimeError("Forum post form not found — you may lack post permission.")
        form = max(forms, key=lambda f: len(f.find_all(["input", "select", "textarea"])))

        form_data: dict[str, str] = {}
        for el in form.find_all(["input", "select", "textarea"]):
            name = _attr(el, "name")
            if not name:
                continue
            # Empty array fields (e.g. tags[]) crash Moodle internals when sent
            # blank: "get_in_or_equal() does not accept empty arrays".
            if name.endswith("[]"):
                continue
            tag = el.name
            input_type = _attr(el, "type", "text").lower()
            if input_type == "submit":
                continue  # cancel/submit buttons — only `submitbutton` is appended below
            if tag == "select":
                selected = el.find("option", selected=True)
                form_data[name] = _attr(selected, "value") if selected else ""
            elif tag == "textarea":
                form_data[name] = el.get_text()
            elif input_type == "checkbox":
                if el.get("checked") is not None:
                    form_data[name] = _attr(el, "value", "1")
            elif input_type == "radio":
                if el.get("checked") is not None:
                    form_data[name] = _attr(el, "value")
            else:
                form_data[name] = _attr(el, "value")

        # Upload attachments into the draft area scraped from this form.
        if attachment_paths:
            draft_itemid = form_data.get("attachments", "")
            if not draft_itemid:
                raise RuntimeError(
                    "Forum post form has no `attachments` draft itemid — this forum may not allow attachments."
                )
            for p in attachment_paths:
                self._upload_to_draft(soup, draft_itemid, p)

        # Patch the fields the UI would fill in.
        form_data["subject"] = subject
        form_data["message[text]"] = message
        form_data["message[format]"] = str(message_format)
        form_data["discussionsubscribe"] = "1" if subscribe else "0"
        form_data["mailnow"] = "1" if mail_now else "0"
        form_data["pinned"] = "1" if pinned else "0"
        form_data["submitbutton"] = "Post to forum"

        # Discover discussion id: snapshot existing ids before, diff after.
        before = self._snapshot_discussion_ids(forum_cmid)

        post_url = f"{self.base_url}/mod/forum/post.php"
        resp = self._post_form(post_url, form_data, referer=resp_get.url)
        if resp.status_code >= 400:
            raise RuntimeError(f"post.php returned HTTP {resp.status_code}")
        if "login" in resp.url:
            raise RuntimeError(f"Session expired during forum post.\n{_SESSION_EXPIRED}")
        if "post.php" in resp.url:
            # Still on the form page — validation error.
            err_soup = BeautifulSoup(resp.text, "html.parser")
            for el in err_soup.find_all(class_=["alert-danger", "formerror", "error"]):
                text = el.get_text(separator=" ", strip=True)
                if text:
                    raise RuntimeError(f"Moodle rejected the post: {text}")
            raise RuntimeError("Moodle rejected the post — unknown validation error.")

        # Try to extract discussion id from redirect URL first.
        m = re.search(r"[?&]d=(\d+)", resp.url)
        if m:
            return int(m.group(1))

        # Fallback: compare before/after snapshots.
        after = self._snapshot_discussion_ids(forum_cmid)
        new_ids = sorted(after - before)
        if new_ids:
            return new_ids[-1]
        raise RuntimeError("Post succeeded but could not determine the new discussion id.")

    def _snapshot_discussion_ids(self, forum_cmid: Cmid) -> set[int]:
        """Return the set of discussion ids currently visible on /mod/forum/view.php.

        Best-effort: modern Moodle templates fill this list via JS, so the set
        may be empty until a discussion exists (the server does embed direct
        discuss.php links for the first row in some themes). Safe to call even
        when listing isn't otherwise supported."""
        try:
            resp = self._session.get(
                f"{self.base_url}/mod/forum/view.php",
                params={"id": int(forum_cmid)},
            )
        except Exception:
            return set()
        ids: set[int] = set()
        for m in re.finditer(r"discuss\.php\?d=(\d+)", resp.text):
            ids.add(int(m.group(1)))
        for m in re.finditer(r'data-discussionid="(\d+)"', resp.text):
            ids.add(int(m.group(1)))
        return ids

    def get_discussion_posts(self, discussion_id: int) -> list[ForumPost]:
        """Scrape /mod/forum/discuss.php?d=ID for every post in a discussion.

        Returns the root post followed by any replies, in rendered order.
        Each post's `parentid` is 0 for the thread starter, non-zero otherwise.
        """
        url = f"{self.base_url}/mod/forum/discuss.php"
        resp = self._session.get(url, params={"d": int(discussion_id)})
        if "login" in resp.url:
            raise RuntimeError(f"Session expired while loading discussion {discussion_id}.\n{_SESSION_EXPIRED}")
        if resp.status_code == 404:
            raise RuntimeError(f"Discussion {discussion_id} not found.")
        soup = BeautifulSoup(resp.text, "html.parser")

        posts: list[ForumPost] = []
        # Modern Moodle wraps each post in <article data-post-id="..."> inside
        # a container with data-region="post-*". Older themes use div.forumpost.
        post_nodes = soup.find_all("article", attrs={"data-post-id": True})
        if not post_nodes:
            post_nodes = soup.find_all(attrs={"data-region": "post"})
        if not post_nodes:
            post_nodes = soup.find_all(class_="forumpost")

        for node in post_nodes:
            post_id_raw = _attr(node, "data-post-id") or _attr(node, "id").replace("p", "")
            post_id = _json_int(post_id_raw)
            parent_id = _json_int(_attr(node, "data-parent-post-id") or _attr(node, "data-parent"))

            # Subject
            subj_el = (
                node.find(attrs={"data-region-content": "subject"})
                or node.find(class_="subject")
                or node.find("h3")
                or node.find("h4")
            )
            subject = subj_el.get_text(strip=True) if subj_el else ""

            # Author
            author_el = (
                node.find(attrs={"data-region": "author-name"})
                or node.find(class_="author")
            )
            author_fullname = author_el.get_text(strip=True) if author_el else ""
            # Strip trailing "by " prefix Moodle sometimes adds.
            author_fullname = re.sub(r"^by\s+", "", author_fullname, flags=re.IGNORECASE)

            # Posted time
            time_el = node.find("time") or node.find(class_="time")
            timecreated_str = ""
            timecreated = 0
            if time_el is not None:
                dt_attr = _attr(time_el, "datetime")
                if dt_attr:
                    try:
                        ts = datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
                        timecreated = int(ts.timestamp())
                        timecreated_str = ts.strftime("%Y-%m-%d %H:%M")
                    except ValueError:
                        timecreated_str = time_el.get_text(strip=True)
                else:
                    timecreated_str = time_el.get_text(strip=True)

            # Body
            body_el = (
                node.find(attrs={"data-region": "post-content-container"})
                or node.find(class_="post-content-container")
                or node.find(class_="posting")
                or node.find(class_="text_to_html")
            )
            if body_el is None:
                # Fallback — strip subject/author/time from the article text.
                for strip in [subj_el, author_el, time_el]:
                    if strip is not None:
                        strip.decompose()
                message = node.get_text(separator="\n", strip=True)
            else:
                message = body_el.decode_contents()

            post: ForumPost = {
                "id": post_id,
                "discussionid": int(discussion_id),
                "parentid": parent_id,
                "subject": subject,
                "message": message.strip(),
                "messageformat": 1,
                "timecreated": timecreated,
                "timecreated_str": timecreated_str,
                "author_fullname": author_fullname,
            }
            posts.append(post)
        return posts

    def get_discussion_root_post_id(self, discussion_id: int) -> int:
        """Return the id of a discussion's root (first) post."""
        for p in self.get_discussion_posts(discussion_id):
            if not p.get("parentid"):  # 0 → root
                pid = p.get("id")
                if pid:
                    return pid
        raise RuntimeError(f"No root post found for discussion {discussion_id}")

    def delete_discussion(self, discussion_id: int) -> None:
        """Delete a forum discussion by deleting its root post.

        Uses /mod/forum/post.php?delete=POSTID — AJAX `mod_forum_delete_post`
        isn't registered on every Moodle install, so scraping the UI delete
        flow is the portable path.
        """
        post_id = self.get_discussion_root_post_id(discussion_id)
        url = f"{self.base_url}/mod/forum/post.php"
        # Confirm step: POST with delete=ID, sesskey, confirm=ID
        resp = self._post_form(
            url,
            {"delete": str(post_id), "confirm": str(post_id), "sesskey": self.sesskey},
            referer=f"{url}?delete={post_id}",
        )
        if resp.status_code == 404:
            raise RuntimeError(f"/mod/forum/post.php returned 404 when deleting post {post_id}")
        if "login" in resp.url:
            raise RuntimeError(f"Session expired while deleting discussion {discussion_id}.\n{_SESSION_EXPIRED}")
        soup = BeautifulSoup(resp.text, "html.parser")
        for el in soup.find_all(class_=["alert-danger", "error"]):
            text = el.get_text(separator=" ", strip=True)
            if text:
                raise RuntimeError(f"Moodle refused to delete post {post_id}: {text}")

    def update_discussion(self, discussion_id: int, subject: str, message: str) -> None:
        """Edit a discussion's first post (subject + HTML message).

        Scrapes /mod/forum/post.php?edit=POSTID, patches the subject/message
        fields, POSTs the form back. Other fields (mail_now, attachments) are
        left as-is.
        """
        post_id = self.get_discussion_root_post_id(discussion_id)
        get_url = f"{self.base_url}/mod/forum/post.php"
        resp_get = self._session.get(get_url, params={"edit": post_id})
        if "login" in resp_get.url:
            raise RuntimeError(f"Session expired while loading post {post_id}.\n{_SESSION_EXPIRED}")
        soup = BeautifulSoup(resp_get.text, "html.parser")
        forms = soup.find_all("form")
        if not forms:
            raise RuntimeError(f"post.php?edit={post_id} returned no form")
        form = max(forms, key=lambda f: len(f.find_all(["input", "select", "textarea"])))

        data: dict[str, str] = {}
        for el in form.find_all(["input", "select", "textarea"]):
            name = _attr(el, "name")
            if not name:
                continue
            tag = el.name
            input_type = _attr(el, "type", "text").lower()
            if input_type == "submit":
                continue
            if tag == "select":
                selected = el.find("option", selected=True)
                data[name] = _attr(selected, "value") if selected else ""
            elif tag == "textarea":
                data[name] = el.get_text()
            elif input_type == "checkbox":
                if el.get("checked") is not None:
                    data[name] = _attr(el, "value", "1")
            elif input_type == "radio":
                if el.get("checked") is not None:
                    data[name] = _attr(el, "value")
            else:
                data[name] = _attr(el, "value")

        data["subject"] = subject
        data["message[text]"] = message
        data["message[format]"] = "1"  # HTML
        resp = self._post_form(get_url, data, referer=f"{get_url}?edit={post_id}")
        if "post.php" in resp.url and resp.status_code == 200:
            soup2 = BeautifulSoup(resp.text, "html.parser")
            for el in soup2.find_all(class_=["alert-danger", "formerror", "error"]):
                text = el.get_text(separator=" ", strip=True)
                if text:
                    raise RuntimeError(f"Moodle rejected edit of post {post_id}: {text}")

    def list_forum_discussions(self, forum_cmid: Cmid, limit: int = 20) -> list[Discussion]:
        """Scrape /mod/forum/view.php for recent discussions (no webservices).

        Walks the forum view page to enumerate discussion ids, then fetches
        /mod/forum/discuss.php for each to populate subject/author/time. This
        is O(N+1) HTTP requests but works on Moodle installs where forum
        webservices are disabled.

        Returns an empty list (not an error) when the forum is empty or when
        the theme renders discussions purely via client-side JS.
        """
        ids = sorted(self._snapshot_discussion_ids(forum_cmid))
        if not ids:
            return []
        out: list[Discussion] = []
        for did in ids[-limit:][::-1]:  # newest-id first, capped at limit
            try:
                posts = self.get_discussion_posts(did)
            except RuntimeError:
                continue
            if not posts:
                continue
            root = posts[0]
            out.append(Discussion(
                id=did,
                name=root.get("subject", ""),
                userfullname=root.get("author_fullname", ""),
                timemodified=root.get("timecreated_str", ""),
                pinned=False,  # not reliably detectable without JS/webservice
                message=root.get("message", ""),
            ))
        return out

    # ── Course content ────────────────────────────────────────────────────────

    def get_course_sections(self, course_id: CourseId, fetch_settings: bool = False) -> list[CourseSection]:
        """Scrape /course/view.php and return all sections with their modules.

        Section name from h3; summary from div.summary.
        Module type from modtype_X CSS class; visibility from hiddenactivity class.
        Module description from div.contentafterlink (inline description if set).
        Due dates are NOT populated here -- call get_course_assignments() and merge.

        fetch_settings=True makes one extra HTTP request per module to populate the
        settings dict with all curated per-type fields (description, dates, grade, etc.).
        Only use this for content pull -- it is too slow for diff/push comparisons.
        """
        soup = self._get_soup(
            f"{self.base_url}/course/view.php",
            params={"id": course_id},
            context=f"course {course_id}",
        )

        sections: list[CourseSection] = []
        for sec_el in soup.find_all(attrs={"data-for": "section"}):
            sec_id = SectionId(int(_attr(sec_el, "data-id")))
            sec_num = int(_attr(sec_el, "data-number", "0"))

            # Section name from h3; fall back to data-number label
            h3 = sec_el.find("h3")
            sec_name = h3.get_text(strip=True) if h3 else f"Section {sec_num}"

            # Section summary/description from div.summary
            summary_el = sec_el.find("div", class_="summary")
            sec_summary = summary_el.get_text(separator=" ", strip=True) if summary_el else ""

            # Section visibility: hidden sections have class "hidden" on the li
            sec_classes = _classes(sec_el)
            sec_visible = "hidden" not in sec_classes

            modules: list[CourseModule] = []
            for act_el in sec_el.find_all("li", class_="activity"):
                cmid_str = _attr(act_el, "data-id")
                if not cmid_str:
                    continue
                cmid = Cmid(int(cmid_str))

                act_classes = _classes(act_el)
                modname = next(
                    (c.removeprefix("modtype_") for c in act_classes if c.startswith("modtype_")),
                    "unknown",
                )

                # Name: prefer data-activityname (works for all types including labels),
                # then fall back to span.instancename with accesshide spans removed.
                activity_item = act_el.find("div", class_="activity-item")
                data_name = _attr(activity_item, "data-activityname") if activity_item else ""
                if data_name:
                    mod_name = data_name
                else:
                    name_el = act_el.find("span", class_="instancename")
                    if name_el:
                        for hidden in name_el.find_all("span"):
                            if "accesshide" in " ".join(_classes(hidden)):
                                hidden.decompose()
                        mod_name = name_el.get_text(strip=True)
                    else:
                        mod_name = act_el.get_text(strip=True)[:60]

                # Module visibility: hidden items have hiddenactivity on the inner div
                activity_div = act_el.find("div", class_="activity-item")
                mod_visible = True
                if activity_div:
                    div_classes = _classes(activity_div)
                    mod_visible = "hiddenactivity" not in div_classes

                # Deeplink URL from the primary anchor
                link = act_el.find("a", class_="aalink")
                mod_url = _attr(link, "href") if link else ""

                # Inline description from contentafterlink div
                desc_el = act_el.find("div", class_="contentafterlink")
                mod_description = desc_el.get_text(separator=" ", strip=True) if desc_el else ""

                settings: dict[str, object] = {}
                if fetch_settings:
                    try:
                        settings = _build_module_settings(self.get_module_form(cmid), modname)
                    except Exception:
                        pass  # best-effort; never block the pull

                modules.append({
                    "cmid": cmid,
                    "name": mod_name,
                    "modname": modname,
                    "visible": mod_visible,
                    "url": mod_url,
                    "description": mod_description,
                    "due_date": "",
                    "settings": settings,
                })

            sections.append({
                "id": sec_id,
                "number": sec_num,
                "name": sec_name,
                "summary": sec_summary,
                "visible": sec_visible,
                "modules": modules,
            })

        return sections

    def set_module_visible(self, cmid: Cmid, visible: bool) -> None:
        """Toggle module visibility via the modedit form (no AJAX needed)."""
        self.update_module(cmid, {"visible": "1" if visible else "0"})

    def set_section_visible(self, section_id: SectionId, visible: bool) -> None:
        """Toggle section visibility via /course/editsection.php form."""
        self._edit_section_form(section_id, {"visible": "1" if visible else "0"})

    def move_section(self, course_id: CourseId, section_id: SectionId, before_section_id: SectionId) -> None:
        """Move a section to appear immediately before before_section_id.

        Uses core_courseformat_update_course section_move action (Moodle 4.x).
        Unlike module moves, there is no valid "end" sentinel — callers must
        ensure before_section_id is a real section in the same course.
        """
        self.ajax("core_courseformat_update_course", {
            "action": "section_move",
            "courseid": int(course_id),
            "ids": [int(section_id)],
            "targetsectionid": int(before_section_id),
        })

    def move_module(self, course_id: CourseId, cmid: Cmid, target_cmid: int, section_id: SectionId) -> None:
        """Move a module to a new position within a section.

        target_cmid=0 appends to the end; any other value places the module
        immediately before that cmid. Uses core_courseformat_update_course
        with the cm_move action (Moodle 4.x format_topics stateactions).
        """
        self.ajax("core_courseformat_update_course", {
            "action": "cm_move",
            "courseid": int(course_id),
            "ids": [int(cmid)],
            "targetsectionid": int(section_id),
            "targetcmid": target_cmid,
        })

    def rename_module(self, cmid: Cmid, name: str) -> None:
        """Rename a module via the modedit form (no AJAX needed)."""
        self.update_module(cmid, {"name": name})

    def rename_section(self, section_id: SectionId, name: str) -> None:
        """Rename a section via /course/editsection.php form."""
        self._edit_section_form(section_id, {"name": name})

    def _edit_section_form(self, section_id: SectionId, changes: dict[str, str]) -> None:
        """Scrape /course/editsection.php for `section_id`, apply `changes`, POST back.

        Recognised `changes` keys: `name` (section title), `visible` ("0"/"1"),
        `summary` (section description). Unknown keys are passed through as
        raw form fields.
        """
        get_url = f"{self.base_url}/course/editsection.php"
        params = {"id": int(section_id), "sr": 0}
        resp_get = self._session.get(get_url, params=params)
        if "login" in resp_get.url:
            raise RuntimeError(f"Session expired loading editsection form.\n{_SESSION_EXPIRED}")
        if resp_get.status_code != 200:
            raise RuntimeError(
                f"editsection.php returned {resp_get.status_code} for section_id={section_id}."
            )
        soup = BeautifulSoup(resp_get.text, "html.parser")
        form_data = _parse_modedit_form(soup, f"editsection?id={section_id}")

        for key, value in changes.items():
            if key == "name":
                # Custom section name — Moodle renders two fields:
                #   name_customize=1 (on/off), name (the value)
                form_data["name_customize"] = "1"
                form_data["name"] = value
            elif key == "visible":
                form_data["visible"] = value
            elif key == "summary":
                form_data["summary_editor[text]"] = value
                form_data["summary_editor[format]"] = form_data.get("summary_editor[format]", "1")
            else:
                form_data[key] = value

        resp = self._post_form(get_url, form_data, referer=get_url)
        if "editsection.php" in resp.url and resp.status_code == 200:
            err_soup = BeautifulSoup(resp.text, "html.parser")
            msg = ""
            for cand in err_soup.find_all(class_=re.compile(r"alert-danger|errormessage|formerror")):
                txt = cand.get_text(" ", strip=True)
                if txt:
                    msg = txt
                    break
            if msg:
                raise RuntimeError(f"Section edit rejected: {msg}")

    def delete_module(self, cmid: Cmid) -> None:
        """Delete a module via the legacy /course/mod.php endpoint.

        Two-step: GET shows a confirmation page with a hidden token; POST it
        back to actually delete. Works on every Moodle version that has the
        course module manager (i.e. all of them).
        """
        sess = self.refresh_sesskey() or ""
        confirm_url = f"{self.base_url}/course/mod.php"
        resp = self._session.get(confirm_url, params={"delete": int(cmid), "sesskey": sess})
        if "login" in resp.url:
            raise RuntimeError(f"Session expired deleting module.\n{_SESSION_EXPIRED}")
        soup = BeautifulSoup(resp.text, "html.parser")

        # Find the confirmation form — typically POSTs to /course/mod.php with
        # delete=<cmid>&confirm=1&sesskey=...
        forms = soup.find_all("form")
        confirm_form = None
        for f in forms:
            inputs = {str(i.get("name") or ""): str(i.get("value", "") or "")
                      for i in f.find_all("input")}
            if str(inputs.get("delete", "")) == str(int(cmid)) and "confirm" in inputs:
                confirm_form = f
                break

        if confirm_form is None:
            # Some Moodle versions skip the confirm page and delete on GET.
            # Verify by re-fetching the section and checking the cmid is gone.
            return

        action = str(confirm_form.get("action") or confirm_url)
        if not action.startswith("http"):
            action = f"{self.base_url}{action}"
        form_data = {str(i.get("name") or ""): str(i.get("value", "") or "")
                     for i in confirm_form.find_all("input")
                     if i.get("name")}
        resp2 = self._post_form(action, form_data, referer=resp.url)
        if resp2.status_code >= 400:
            raise RuntimeError(
                f"Module delete confirmation returned {resp2.status_code} for cmid={cmid}."
            )

    # ── Module form (modedit.php) ─────────────────────────────────────────────

    def _scrape_modedit_form(self, params: dict[str, str | int]) -> dict[str, str]:
        """Scrape /course/modedit.php with the given query params and return form fields.

        Used for both the edit form (?update=<cmid>) and the add form
        (?add=<modname>&course=<id>&section=<n>).
        """
        get_url = f"{self.base_url}/course/modedit.php"
        resp = self._session.get(get_url, params=params)
        if "login" in resp.url:
            raise RuntimeError(f"Session expired while loading modedit form.\n{_SESSION_EXPIRED}")
        soup = BeautifulSoup(resp.text, "html.parser")
        return _parse_modedit_form(soup, str(params))

    def _upload_to_draft(self, soup: BeautifulSoup, draft_itemid: str, file_path: str) -> None:
        """Upload a local file to a Moodle draft area.

        Discovers the upload repo_id and course/user context from the embedded
        filepicker config, then POSTs multipart to /repository/repository_ajax.php.
        """
        import os

        html = str(soup)
        m = re.search(
            r'\{[^{}]*?"type"\s*:\s*"upload"[^{}]*?"id"\s*:\s*"?(\d+)',
            html,
        ) or re.search(
            r'\{[^{}]*?"id"\s*:\s*"?(\d+)"?[^{}]*?"type"\s*:\s*"upload"',
            html,
        )
        if not m:
            raise RuntimeError("Could not find 'upload' repository id in modedit page.")
        repo_id = m.group(1)

        ctx_match = re.search(r'"contextid"\s*:\s*"?(\d+)', html)
        ctx_id = ctx_match.group(1) if ctx_match else ""

        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        filename = os.path.basename(file_path)
        # Use a clean requests session — the shared session has Content-Type:
        # application/json, which breaks the multipart upload.
        import requests
        s = requests.Session()
        for ck in self._session.cookies:
            if ck.value is not None:
                s.cookies.set(ck.name, ck.value)
        s.headers.update({
            "User-Agent": self._session.headers["User-Agent"],
            "Referer": f"{self.base_url}/course/modedit.php",
        })
        with open(file_path, "rb") as f:
            files = {"repo_upload_file": (filename, f, "application/octet-stream")}
            data = {
                "sesskey": self.sesskey,
                "repo_id": repo_id,
                "itemid": str(draft_itemid),
                "savepath": "/",
                "title": filename,
                "ctx_id": ctx_id,
                "license": "unknown",
                "author": "",
            }
            resp = s.post(
                f"{self.base_url}/repository/repository_ajax.php?action=upload",
                data=data, files=files,
            )
        if resp.status_code != 200:
            raise RuntimeError(f"Draft upload failed: HTTP {resp.status_code} {resp.text[:200]}")
        try:
            result = resp.json()
        except ValueError:
            raise RuntimeError(f"Draft upload returned non-JSON: {resp.text[:200]}")
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(f"Draft upload rejected: {result['error']}")

    def get_module_form(self, cmid: Cmid) -> dict[str, str]:
        """Scrape the modedit.php edit form for a module and return all field values.

        Always fetches fresh — the introeditor draft itemid expires and must not be cached.
        The returned dict contains every form field (hidden + visible), ready to POST back.
        """
        return self._scrape_modedit_form({"update": int(cmid), "return": 0})

    def create_module(
            self,
            course_id: CourseId,
            section_num: int,
            modname: str,
            name: str,
            settings: dict[str, Any] | None = None,
            file_path: str | None = None,
    ) -> Cmid:
        """Create a new course module.

        section_num — 0-indexed section number shown in `content list`.
        modname     — Moodle module type (label, page, url, forum, assign, quiz, resource, ...).
        name        — human-readable module name (ignored by labels, which use the intro).
        settings    — optional dict of curated settings (see _SETTINGS_SCHEMA).
        file_path   — local file to upload for `resource` (and any other filemanager-
                      backed module). The file is pushed into the form's draft area
                      before the form is POSTed.

        Returns the cmid of the newly created module.
        """
        get_url = f"{self.base_url}/course/modedit.php"
        get_params = {
            "add": modname, "type": "", "course": int(course_id),
            "section": section_num, "return": 0, "sr": 0,
        }
        resp_get = self._session.get(get_url, params=get_params)
        if "login" in resp_get.url:
            raise RuntimeError(f"Session expired while loading modedit form.\n{_SESSION_EXPIRED}")
        soup = BeautifulSoup(resp_get.text, "html.parser")
        form_data = _parse_modedit_form(soup, f"add={modname}")

        if file_path:
            if modname != "resource":
                raise ValueError(
                    f"file_path is only supported for 'resource' modules, not {modname!r}."
                )
            draft_itemid = form_data.get("files")
            if not draft_itemid:
                raise RuntimeError("modedit form has no 'files' draft itemid — cannot upload.")
            self._upload_to_draft(soup, draft_itemid, file_path)
            if not name:
                import os
                name = os.path.splitext(os.path.basename(file_path))[0]
            form_data["name"] = name

        if name and "name" in form_data:
            form_data["name"] = name

        if settings:
            for key, value in _settings_to_form(modname, settings).items():
                val = str(value) if value else ""
                if val and _DATE_RE.match(val):
                    form_data.update(_datetime_to_form(val, key))
                elif not val and f"{key}[enabled]" in form_data:
                    form_data[f"{key}[enabled]"] = ""
                else:
                    form_data[key] = val

        resp = self._post_form(get_url, form_data, referer=get_url)
        if resp.status_code == 404:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".html",
                prefix=f"moodlectl_404_new_{modname}_",
            )
            tmp.write(resp.text.encode("utf-8", errors="replace"))
            tmp.close()
            raise RuntimeError(
                f"modedit.php POST returned 404 for new {modname} in course {course_id}.\n"
                f"  resp url: {resp.url}\n"
                f"  body:     {tmp.name}\n"
                f"Likely causes: session expired, or teacher lacks 'Manage activities'."
            )
        if "modedit.php" in resp.url and resp.status_code == 200:
            import tempfile
            soup = BeautifulSoup(resp.text, "html.parser")
            msg = ""
            for candidate in [
                *soup.find_all(id=re.compile(r"^id_error_")),
                *soup.find_all(class_="formerror"),
                *soup.find_all(class_="alert-danger"),
                *soup.find_all(class_="error"),
            ]:
                text = candidate.get_text(separator=" ", strip=True)
                if text:
                    msg = text
                    break
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".html",
                prefix=f"moodlectl_err_new_{modname}_",
            )
            tmp.write(resp.text.encode("utf-8", errors="replace"))
            tmp.close()
            raise RuntimeError(
                f"Moodle rejected new {modname} module: {msg or 'unknown error'}\n"
                f"Full response saved to: {tmp.name}"
            )

        # Locate the new cmid — Moodle typically redirects to course view.
        # Strategy: re-scrape sections, find modules in target section with matching
        # name + modname, pick the one not previously present (highest cmid wins
        # if multiple with same name).
        sections = self.get_course_sections(course_id)
        target = next((s for s in sections if s["number"] == section_num), None)
        if target is None:
            raise RuntimeError(f"Could not find section {section_num} after create")
        candidates = [
            m for m in target["modules"]
            if m["modname"] == modname and (not name or m["name"] == name or modname == "label")
        ]
        if not candidates:
            raise RuntimeError(
                f"Created module {modname} not found in section {section_num} after POST. "
                f"Response URL: {resp.url}"
            )
        return max(candidates, key=lambda m: int(m["cmid"]))["cmid"]

    def update_module(
            self,
            cmid: Cmid,
            changes: dict[str, str],
            rescale: str = "no",
    ) -> None:
        """Apply field changes to a module via the modedit.php form.

        Scrapes the form fresh (to get current values and a valid draft itemid),
        merges `changes`, then POSTs. Raises RuntimeError if Moodle reports an error.

        rescale — when `max_grade` is among `changes` and the activity already
        has awarded grades, Moodle demands a "rescale existing grades?" choice.
        "no" keeps existing grades as-is; "yes" rescales them to the new max.
        """
        get_url = f"{self.base_url}/course/modedit.php"
        form_data = self.get_module_form(cmid)
        for key, value in changes.items():
            val = str(value) if value else ""
            if val and _DATE_RE.match(val):
                # Datetime string -> expand to date group sub-fields and enable
                form_data.update(_datetime_to_form(val, key))
            elif not val and f"{key}[enabled]" in form_data:
                # Empty value for a date group prefix -> disable the date
                form_data[f"{key}[enabled]"] = ""
            else:
                form_data[key] = val
        if "grade[modgrade_point]" in changes:
            form_data["grade[modgrade_rescalegrades]"] = rescale
        resp = self._post_form(f"{self.base_url}/course/modedit.php", form_data, referer=get_url)
        if resp.status_code == 404:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".html",
                prefix=f"moodlectl_404_cmid{cmid}_",
            )
            tmp.write(resp.text.encode("utf-8", errors="replace"))
            tmp.close()
            attempted = ", ".join(sorted(changes.keys())) or "(none)"
            raise RuntimeError(
                f"modedit.php POST returned 404 for cmid={cmid}.\n"
                f"  URL:      POST {self.base_url}/course/modedit.php\n"
                f"  fields:   {attempted}\n"
                f"  resp url: {resp.url}\n"
                f"  body:     {tmp.name}\n"
                f"Likely causes: session expired (re-run 'moodlectl auth login'), "
                f"the module was deleted, or this activity type is not editable "
                f"via modedit.php (e.g. the default 'Announcements' news forum on "
                f"some Moodle installs rejects modedit POSTs — edit it from the UI)."
            )
        # Success: Moodle redirects to the course or module view page.
        # Failure: stays on modedit.php and shows validation errors in HTML.
        if "modedit.php" in resp.url and resp.status_code == 200:
            import tempfile
            soup = BeautifulSoup(resp.text, "html.parser")
            msg = ""
            for candidate in [
                *soup.find_all(id=re.compile(r"^id_error_")),
                *soup.find_all(class_="formerror"),
                *soup.find_all(class_="alert-danger"),
                *soup.find_all(class_="error"),
            ]:
                text = candidate.get_text(separator=" ", strip=True)
                if text:
                    msg = text
                    break
            # Dump response HTML to a temp file so the caller can inspect what Moodle returned.
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html", prefix=f"moodlectl_err_cmid{cmid}_")
            tmp.write(resp.text.encode("utf-8", errors="replace"))
            tmp.close()
            raise RuntimeError(
                f"Moodle rejected the form for cmid={cmid}: {msg or 'unknown error'}\n"
                f"Full response saved to: {tmp.name}"
            )

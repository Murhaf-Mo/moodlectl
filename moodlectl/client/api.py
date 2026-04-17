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
    FileRef,
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
        day   = int(form.get(f"{prefix}[day]",    "1"))
        month = int(form.get(f"{prefix}[month]",  "1"))
        year  = int(form.get(f"{prefix}[year]",   "2000"))
        hour  = int(form.get(f"{prefix}[hour]",   "0"))
        minute = int(form.get(f"{prefix}[minute]","0"))
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
        f"{prefix}[day]":     str(dt.day),
        f"{prefix}[month]":   str(dt.month),
        f"{prefix}[year]":    str(dt.year),
        f"{prefix}[hour]":    str(dt.hour),
        f"{prefix}[minute]":  str(dt.minute),
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
        number   = int(form.get(f"{prefix}[number]",   "0"))
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
            f"{prefix}[enabled]":  "1",
            f"{prefix}[number]":   str(int(mins)),
            f"{prefix}[timeunit]": "60",
        }
    return {
        f"{prefix}[enabled]":  "",
        f"{prefix}[number]":   "0",
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
    "id_number":              ("cmidnumber",          "str"),
    "show_description":       ("showdescription",     "int"),
    "force_language":         ("lang",                "str"),
    # Groups
    "group_mode":             ("groupmode",           "int"),
    "grouping":               ("groupingid",          "int"),
    # Tags
    "tags":                   ("tags",                "tags"),
    # Competencies
    "competency_rule":        ("competency_rule",     "int"),
    # Completion tracking
    "completion":             ("completion",          "int"),   # 0=none 1=manual 2=auto
    "completion_on_view":     ("completionview",      "int"),
    "completion_on_grade":    ("completionusegrade",  "int"),
    "completion_pass_grade":  ("completionpassgrade", "int"),
    "completion_expected":    ("completionexpected",  "datetime"),
}

_SETTINGS_SCHEMA: dict[str, dict[str, tuple[str, str]]] = {
    "assign": {
        **_COMMON_SCHEMA,
        "description":              ("introeditor[text]",                    "str"),
        "due_date":                 ("duedate",                              "datetime"),
        "available_from":           ("allowsubmissionsfromdate",             "datetime"),
        "cut_off":                  ("cutoffdate",                           "datetime"),
        "grading_due":              ("gradingduedate",                       "datetime"),
        "max_grade":                ("grade[modgrade_point]",                "float"),
        "grade_pass":               ("gradepass",                            "float"),
        "grade_category":           ("gradecat",                             "int"),
        "submission_drafts":        ("submissiondrafts",                     "int"),
        "require_statement":        ("requiresubmissionstatement",           "int"),
        "online_text_enabled":      ("assignsubmission_onlinetext_enabled",  "int"),
        "file_enabled":             ("assignsubmission_file_enabled",        "int"),
        "max_files":                ("assignsubmission_file_maxfiles",       "int"),
        "max_file_size":            ("assignsubmission_file_maxsizebytes",   "int"),
        "allowed_file_types":       ("assignsubmission_file_filetypes[filetypes]", "str"),
        "inline_comments":          ("assignfeedback_comments_commentinline","int"),
        "notify_graders":           ("sendnotifications",                    "int"),
        "notify_graders_late":      ("sendlatenotifications",                "int"),
        "notify_students":          ("sendstudentnotifications",             "int"),
        "blind_marking":            ("blindmarking",                         "int"),
        "hide_grader":              ("hidegrader",                           "int"),
        "marking_workflow":         ("markingworkflow",                      "int"),
        "marking_allocation":       ("markingallocation",                    "int"),
        "team_submission":          ("teamsubmission",                       "int"),
        "reopen_attempts":          ("attemptreopenmethod",                  "str"),
        "max_attempts":             ("maxattempts",                          "int"),
        "completion_on_submit":     ("completionsubmit",                     "int"),
        "grading_method":           ("advancedgradingmethod_submissions",    "str"),
    },
    "quiz": {
        **_COMMON_SCHEMA,
        # General
        "description":                  ("introeditor[text]",    "str"),
        # Timing
        "available_from":               ("timeopen",             "datetime"),
        "due_date":                     ("timeclose",            "datetime"),
        "time_limit_mins":              ("timelimit",            "duration_mins"),
        "when_time_expires":            ("overduehandling",      "str"),   # autosubmit|graceperiod|autoabandon
        "grace_period_mins":            ("graceperiod",          "duration_mins"),
        # Grade
        "max_grade":                    ("grade",                "float"),
        "grade_category":               ("gradecat",             "int"),
        "grade_to_pass":                ("gradepass",            "float"),
        "grade_method":                 ("grademethod",          "str"),   # 1=highest 2=avg 3=first 4=last
        "attempts_allowed":             ("attempts",             "int"),
        "delay_1_mins":                 ("delay1",               "duration_mins"),
        "delay_2_mins":                 ("delay2",               "duration_mins"),
        # Layout
        "questions_per_page":           ("questionsperpage",     "int"),
        "navigation_method":            ("navmethod",            "str"),   # free|sequential
        # Question behaviour
        "shuffle_answers":              ("shuffleanswers",       "int"),
        "review_behaviour":             ("preferredbehaviour",   "str"),   # deferredfeedback|immediatefeedback|etc
        "redo_questions":               ("canredoquestions",     "int"),
        # Review options — during attempt
        "review_attempt_during":        ("attemptduring",        "int"),
        # Review options — after closing
        "review_attempt_closed":        ("attemptclosed",        "int"),
        "review_attempt_on_last":       ("attemptonlast",        "int"),
        "review_correctness_closed":    ("correctnessclosed",    "int"),
        "review_marks_closed":          ("marksclosed",          "int"),
        "review_max_marks_closed":      ("maxmarksclosed",       "int"),
        "review_specific_feedback_closed": ("specificfeedbackclosed", "int"),
        "review_general_feedback_closed":  ("generalfeedbackclosed",  "int"),
        "review_right_answer_closed":   ("rightanswerclosed",    "int"),
        "review_overall_feedback_closed":  ("overallfeedbackclosed",  "int"),
        # Appearance
        "show_user_picture":            ("showuserpicture",      "int"),
        "decimal_places":               ("decimalpoints",        "int"),
        "question_decimal_places":      ("questiondecimalpoints","int"),
        "show_blocks":                  ("showblocks",           "int"),
        # Security / restrictions
        "password":                     ("quizpassword",         "str"),
        "network_address":              ("subnet",               "str"),
        "browser_security":             ("browsersecurity",      "str"),
        "start_time_limit_mins":        ("startlimit",           "duration_mins"),
        # Safe Exam Browser
        "seb_require":                  ("seb_requiresafeexambrowser", "str"),
        "seb_show_download_link":       ("seb_showsebdownloadlink",    "int"),
        "seb_allow_quit":               ("seb_allowuserquitseb",       "int"),
        "seb_confirm_quit":             ("seb_userconfirmquit",        "int"),
        "seb_quit_password":            ("seb_quitpassword",           "str"),
        "seb_allow_reload":             ("seb_allowreloadinexam",      "int"),
        "seb_show_taskbar":             ("seb_showsebtaskbar",         "int"),
        "seb_show_reload_button":       ("seb_showreloadbutton",       "int"),
        "seb_show_time":                ("seb_showtime",               "int"),
        "seb_show_keyboard":            ("seb_showkeyboardlayout",     "int"),
        "seb_show_wifi":                ("seb_showwificontrol",        "int"),
        "seb_enable_audio":             ("seb_enableaudiocontrol",     "int"),
        "seb_mute_on_startup":          ("seb_muteonstartup",          "int"),
        "seb_allow_spell_check":        ("seb_allowspellchecking",     "int"),
        "seb_url_filtering":            ("seb_activateurlfiltering",   "int"),
        # Completion (quiz-specific extras beyond _COMMON_SCHEMA)
        "completion_min_attempts":      ("completionminattempts",      "int"),
        "completion_attempts_exhausted":("completionattemptsexhausted","int"),
    },
    "forum": {
        **_COMMON_SCHEMA,
        "description":              ("introeditor[text]",  "str"),
        "forum_type":               ("type",               "str"),
        "max_file_size":            ("maxbytes",           "int"),
        "max_attachments":          ("maxattachments",     "int"),
        "subscription_mode":        ("forcesubscribe",     "str"),  # 0=optional 1=forced 2=auto 3=disabled
        "tracking_type":            ("trackingtype",       "str"),
        "completion_posts":         ("completionposts",    "int"),
        "completion_discussions":   ("completiondiscussions", "int"),
        "completion_replies":       ("completionreplies",  "int"),
    },
    "resource": {
        **_COMMON_SCHEMA,
        "description":   ("introeditor[text]", "str"),
        "display_mode":  ("display",           "int"),   # 0=auto 1=embed 2=force download etc.
        "show_size":     ("showsize",          "int"),
        "show_type":     ("showtype",          "int"),
        "show_date":     ("showdate",          "int"),
    },
    "url": {
        **_COMMON_SCHEMA,
        "description":   ("introeditor[text]", "str"),
        "external_url":  ("externalurl",       "str"),
        "display_mode":  ("display",           "int"),
    },
    "page": {
        **_COMMON_SCHEMA,
        "description":   ("introeditor[text]",        "str"),
        "content":       ("page[text]",               "str"),
        "display_mode":  ("display",                  "int"),
    },
    "label": {
        **_COMMON_SCHEMA,
        "content":       ("introeditor[text]", "str"),
    },
    "assign_default": {
        **_COMMON_SCHEMA,
        "description":   ("introeditor[text]", "str"),
    },
}
_DEFAULT_SCHEMA = _SETTINGS_SCHEMA["assign_default"]

# ── Course-level settings schema (course/edit.php) ────────────────────────────
# type_hint: same as module schema — "str" | "int" | "float" | "datetime" | "tags"
_COURSE_SETTINGS_SCHEMA: dict[str, tuple[str, str]] = {
    # General
    "fullname":                  ("fullname",              "str"),
    "shortname":                 ("shortname",             "str"),
    "id_number":                 ("idnumber",              "str"),
    "visible":                   ("visible",               "int"),
    "start_date":                ("startdate",             "datetime_always"),
    "end_date":                  ("enddate",               "datetime"),
    # Description
    "summary":                   ("summary_editor[text]",  "str"),
    # Course format
    "format":                    ("format",                "str"),   # topics|weeks|social|singleactivity
    "hidden_sections":           ("hiddensections",        "int"),   # 0=collapsed 1=invisible
    "course_layout":             ("coursedisplay",         "int"),   # 0=all on one page 1=one section per page
    # Appearance
    "force_language":            ("lang",                  "str"),
    "announcements_count":       ("newsitems",             "int"),
    "show_gradebook":            ("showgrades",            "int"),
    "show_activity_reports":     ("showreports",           "int"),
    "show_activity_dates":       ("showactivitydates",     "int"),
    # Files and uploads
    "max_upload_size":           ("maxbytes",              "int"),
    # Completion tracking
    "enable_completion":         ("enablecompletion",      "int"),
    "show_completion_conditions":("showcompletionconditions","int"),
    # Groups
    "group_mode":                ("groupmode",             "int"),   # 0=no groups 1=separate 2=visible
    "force_group_mode":          ("groupmodeforce",        "int"),
    "default_grouping":          ("defaultgroupingid",     "int"),
    # Tags
    "tags":                      ("tags",                  "tags"),
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


def _course_settings_to_form(settings: dict[str, Any]) -> dict[str, str]:
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


def _build_module_settings_dynamic(form: dict[str, str]) -> dict[str, Any]:
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
            val = str(value) if value is not None else ""
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
        raw = self.ajax("core_course_get_enrolled_courses_by_timeline_classification", {
            "offset": 0,
            "limit": 0,
            "classification": classification,
            "sort": sort,
            "customfieldname": "",
            "customfieldvalue": "",
            "requiredfields": ["id", "fullname", "shortname", "visible", "enddate"],
        })
        data = cast(dict[str, list[Course]], raw)
        return data["courses"]

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
                        for a in th.find_all("a"):
                            title = _attr(a, "title")
                            if title.startswith("Link to"):
                                name = re.sub(r"^Link to \S+ activity ", "", title).strip()
                                break
                        if not name:
                            raw = th.get_text(separator=" ", strip=True)
                            name = re.sub(
                                r"\s*(Cell actions|Ascending|Descending|Collapse|Expand column)\b.*",
                                "", raw, flags=re.DOTALL,
                            ).strip()
                        columns.append(name or f"col{len(columns)}")

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

        return {"columns": columns, "rows": all_student_rows}

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
                        for hidden in name_el.find_all("span", attrs={"class": lambda c: c and "accesshide" in c}):
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
        action = "show" if visible else "hide"
        self.ajax("core_course_edit_module", {"id": cmid, "action": action})

    def set_section_visible(self, section_id: SectionId, visible: bool) -> None:
        action = "show" if visible else "hide"
        self.ajax("core_course_edit_section", {"id": section_id, "action": action})

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
        self.ajax("core_update_inplace_editable", {
            "component": "core_course",
            "itemtype": "activityname",
            "itemid": cmid,
            "value": name,
        })

    def rename_section(self, section_id: SectionId, name: str) -> None:
        self.ajax("core_update_inplace_editable", {
            "component": "format_topics",
            "itemtype": "sectionname",
            "itemid": section_id,
            "value": name,
        })

    def delete_module(self, cmid: Cmid) -> None:
        self.ajax("core_course_edit_module", {"id": cmid, "action": "delete"})

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

        forms = soup.find_all("form")
        if not forms:
            raise RuntimeError(
                f"modedit.php returned no form for params={params}. "
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
    ) -> Cmid:
        """Create a new course module.

        section_num — 0-indexed section number shown in `content list`.
        modname     — Moodle module type (label, page, url, forum, assign, quiz, resource, ...).
        name        — human-readable module name (ignored by labels, which use the intro).
        settings    — optional dict of curated settings (see _SETTINGS_SCHEMA).

        Returns the cmid of the newly created module.
        """
        get_url = f"{self.base_url}/course/modedit.php"
        form_data = self._scrape_modedit_form({
            "add": modname, "type": "", "course": int(course_id),
            "section": section_num, "return": 0, "sr": 0,
        })

        if name and "name" in form_data:
            form_data["name"] = name

        if settings:
            for key, value in _settings_to_form(modname, settings).items():
                val = str(value) if value is not None else ""
                if val and _DATE_RE.match(val):
                    form_data.update(_datetime_to_form(val, key))
                elif not val and f"{key}[enabled]" in form_data:
                    form_data[f"{key}[enabled]"] = ""
                else:
                    form_data[key] = val

        resp = self._post_form(get_url, form_data, referer=get_url)
        if resp.status_code == 404:
            raise RuntimeError(f"modedit.php POST returned 404 for new {modname} in course {course_id}")
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

    def update_module(self, cmid: Cmid, changes: dict[str, str]) -> None:
        """Apply field changes to a module via the modedit.php form.

        Scrapes the form fresh (to get current values and a valid draft itemid),
        merges `changes`, then POSTs. Raises RuntimeError if Moodle reports an error.
        """
        get_url = f"{self.base_url}/course/modedit.php"
        form_data = self.get_module_form(cmid)
        for key, value in changes.items():
            val = str(value) if value is not None else ""
            if val and _DATE_RE.match(val):
                # Datetime string -> expand to date group sub-fields and enable
                form_data.update(_datetime_to_form(val, key))
            elif not val and f"{key}[enabled]" in form_data:
                # Empty value for a date group prefix -> disable the date
                form_data[f"{key}[enabled]"] = ""
            else:
                form_data[key] = val
        resp = self._post_form(f"{self.base_url}/course/modedit.php", form_data, referer=get_url)
        if resp.status_code == 404:
            raise RuntimeError(f"modedit.php POST returned 404 for cmid={cmid} — check session")
        # Success: Moodle redirects to the course or module view page.
        # Failure: stays on modedit.php and shows validation errors in HTML.
        if "modedit.php" in resp.url and resp.status_code == 200:
            import tempfile, os
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

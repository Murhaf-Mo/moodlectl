from __future__ import annotations

from typing import Any

from moodlectl.types import Cmid, CourseId, CourseModule, CourseSection, MoodleClientProtocol


def get_sections(
        client: MoodleClientProtocol,
        course_id: CourseId,
        section_num: int | None = None,
        modtype: str | None = None,
        show_hidden: bool = True,
) -> list[CourseSection]:
    """Return course sections, with optional filters applied in this layer."""
    sections = client.get_course_sections(course_id)

    if section_num is not None:
        sections = [s for s in sections if s["number"] == section_num]

    if not show_hidden:
        sections = [s for s in sections if s["visible"]]
        sections = [_with_modules(s, [m for m in s["modules"] if m["visible"]]) for s in sections]

    if modtype is not None:
        modtype_lower = modtype.lower()
        sections = [
            _with_modules(s, [m for m in s["modules"] if m["modname"].lower() == modtype_lower])
            for s in sections
        ]

    return sections


def _with_modules(section: CourseSection, modules: list[CourseModule]) -> CourseSection:
    """Return a shallow copy of `section` with `modules` replaced."""
    return CourseSection(
        id=section["id"],
        number=section["number"],
        name=section["name"],
        summary=section["summary"],
        visible=section["visible"],
        modules=modules,
    )


def find_module(
        client: MoodleClientProtocol,
        course_id: CourseId,
        cmid: Cmid,
) -> CourseModule | None:
    """Find a specific module anywhere in the course by cmid."""
    for section in client.get_course_sections(course_id):
        for mod in section["modules"]:
            if mod["cmid"] == cmid:
                return mod
    return None


def _resolve_section(sections: list[CourseSection], section_num: int) -> CourseSection:
    for s in sections:
        if s["number"] == section_num:
            return s
    raise ValueError(f"Section {section_num} not found in course")


def set_module_visible(
        client: MoodleClientProtocol,
        course_id: CourseId,
        cmid: Cmid,
        visible: bool,
) -> None:
    if find_module(client, course_id, cmid) is None:
        raise ValueError(f"Module cmid={cmid} not found in course {course_id}")
    client.set_module_visible(cmid, visible)


def set_section_visible(
        client: MoodleClientProtocol,
        course_id: CourseId,
        section_num: int,
        visible: bool,
) -> None:
    sections = client.get_course_sections(course_id)
    section = _resolve_section(sections, section_num)
    client.set_section_visible(section["id"], visible)


def rename_module(
        client: MoodleClientProtocol,
        course_id: CourseId,
        cmid: Cmid,
        name: str,
) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Module name cannot be empty")
    if find_module(client, course_id, cmid) is None:
        raise ValueError(f"Module cmid={cmid} not found in course {course_id}")
    client.rename_module(cmid, name)


def rename_section(
        client: MoodleClientProtocol,
        course_id: CourseId,
        section_num: int,
        name: str,
) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Section name cannot be empty")
    sections = client.get_course_sections(course_id)
    section = _resolve_section(sections, section_num)
    client.rename_section(section["id"], name)


def delete_module(
        client: MoodleClientProtocol,
        course_id: CourseId,
        cmid: Cmid,
) -> None:
    if find_module(client, course_id, cmid) is None:
        raise ValueError(f"Module cmid={cmid} not found in course {course_id}")
    client.delete_module(cmid)


def get_module_settings(
        client: MoodleClientProtocol,
        course_id: CourseId,
        cmid: Cmid,
) -> dict[str, str]:
    """Return the raw modedit.php form fields for a module (all 100+ fields)."""
    if find_module(client, course_id, cmid) is None:
        raise ValueError(f"Module cmid={cmid} not found in course {course_id}")
    return client.get_module_form(cmid)


_VALID_MODNAMES = {
    "assign", "quiz", "forum", "resource", "url", "page",
    "label", "book", "chat", "choice", "feedback", "folder",
    "glossary", "h5pactivity", "imscp", "lesson", "lti",
    "scorm", "survey", "wiki", "workshop", "data",
}


def create_module(
        client: MoodleClientProtocol,
        course_id: CourseId,
        section_num: int,
        modname: str,
        name: str,
        settings: dict[str, Any] | None = None,
        file_path: str | None = None,
) -> Cmid:
    """Create a new module and return its cmid.

    modname is the Moodle activity plugin name (label, page, url, assign, quiz, ...).
    name is required for everything except labels (where the content body is the display).
    settings is the curated settings dict (same keys accepted by `content set`).
    file_path uploads a local file into the module's draft area — only valid for `resource`.
    """
    modname = modname.strip().lower()
    if modname not in _VALID_MODNAMES:
        raise ValueError(
            f"Unknown module type {modname!r}. "
            f"Supported: {', '.join(sorted(_VALID_MODNAMES))}"
        )
    if file_path and modname != "resource":
        raise ValueError(f"--file is only valid for resource modules, not {modname!r}")
    name = (name or "").strip()
    if not name and modname != "label" and not file_path:
        raise ValueError(f"--name is required for {modname} modules")
    sections = client.get_course_sections(course_id)
    if not any(s["number"] == section_num for s in sections):
        raise ValueError(f"Section {section_num} not found in course {course_id}")
    return client.create_module(
        course_id, section_num, modname, name, settings or {}, file_path=file_path,
    )


def set_module_setting(
        client: MoodleClientProtocol,
        course_id: CourseId,
        cmid: Cmid,
        field: str,
        value: str,
) -> None:
    """Set a single setting on a module.

    field can be either a human-readable shortcut (e.g. 'due_date', 'max_grade')
    or any raw form field name visible in `content settings` (e.g. 'timelimit',
    'assignsubmission_file_maxfiles'). Dates accept 'YYYY-MM-DD HH:MM' format.
    """
    from moodlectl.client.api import _settings_to_form

    mod = find_module(client, course_id, cmid)
    if mod is None:
        raise ValueError(f"Module cmid={cmid} not found in course {course_id}")

    form_changes = _settings_to_form(mod["modname"], {field: value})
    client.update_module(cmid, form_changes)

from __future__ import annotations

from typing import Any

from moodlectl.types import Cmid, CourseId, CourseModule, CourseSection, MoodleClientProtocol, SectionId


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
        sections = [
            {**s, "modules": [m for m in s["modules"] if m["visible"]]}
            for s in sections
        ]

    if modtype is not None:
        modtype_lower = modtype.lower()
        sections = [
            {**s, "modules": [m for m in s["modules"] if m["modname"].lower() == modtype_lower]}
            for s in sections
        ]

    return sections


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

import pytest

from moodlectl.features.announcements import (
    _format_to_int,
    find_news_forum_cmid,
)
from moodlectl.types import Cmid, CourseId, CourseModule, CourseSection, SectionId


def _mod(cmid: int, name: str, modname: str = "forum") -> CourseModule:
    return CourseModule(
        cmid=Cmid(cmid),
        name=name,
        modname=modname,
        visible=True,
        url="",
        description="",
        due_date="",
        settings={},
    )


def _section(number: int, modules: list[CourseModule]) -> CourseSection:
    return CourseSection(
        id=SectionId(number + 7000),
        number=number,
        name=f"Section {number}",
        summary="",
        visible=True,
        modules=modules,
    )


class _FakeClient:
    def __init__(self, sections: list[CourseSection]) -> None:
        self._sections = sections

    def get_course_sections(self, course_id: CourseId) -> list[CourseSection]:
        return self._sections


def test_find_news_forum_cmid_prefers_named_match() -> None:
    sections = [
        _section(0, [
            _mod(10, "Q&A Forum"),
            _mod(11, "Announcements"),
        ]),
        _section(1, [_mod(12, "Some other forum")]),
    ]
    client = _FakeClient(sections)
    assert find_news_forum_cmid(client, CourseId(590)) == 11  # type: ignore[arg-type]


def test_find_news_forum_cmid_arabic_name() -> None:
    sections = [_section(0, [_mod(20, "الإعلانات")])]
    assert find_news_forum_cmid(_FakeClient(sections), CourseId(590)) == 20  # type: ignore[arg-type]


def test_find_news_forum_cmid_falls_back_to_section_zero() -> None:
    sections = [
        _section(0, [_mod(30, "General forum")]),
        _section(1, [_mod(31, "Weekly Q&A")]),
    ]
    assert find_news_forum_cmid(_FakeClient(sections), CourseId(590)) == 30  # type: ignore[arg-type]


def test_find_news_forum_cmid_raises_when_no_forum() -> None:
    sections = [_section(0, [_mod(40, "Readings", modname="resource")])]
    with pytest.raises(ValueError, match="no forum"):
        find_news_forum_cmid(_FakeClient(sections), CourseId(590))  # type: ignore[arg-type]


def test_format_to_int_maps_known_names() -> None:
    assert _format_to_int("html") == 1
    assert _format_to_int("MARKDOWN") == 4
    assert _format_to_int("plain") == 2
    assert _format_to_int("moodle") == 0


def test_format_to_int_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown message format"):
        _format_to_int("rich-text")

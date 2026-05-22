"""Tests for `features/gradebook.py` pull() and render_tree().

Phase 1: read-only path only. A `_FakeClient` returns a hand-crafted
GradeTree (skipping the live tree-page scrape) and stub form responses, so
the test exercises the YAML serialiser + enrichment loop end-to-end without
HTTP.
"""
from __future__ import annotations

from typing import Any

import yaml

from moodlectl.features import gradebook as gradebook_feature
from moodlectl.types import (
    CourseId,
    GradeCategory,
    GradeCategoryId,
    GradeItem,
    GradeItemId,
    GradeTree,
)


def _build_tree() -> GradeTree:
    """Tiny 1-subcategory tree: course-total → Assignments cat → 2 items + 1 manual item at root."""
    asg_items: list[GradeItem] = [
        {
            "eid": "ig101", "item_id": GradeItemId(101), "parent_cat_id": GradeCategoryId(2),
            "name": "Asg 1", "kind": "assign", "cmid": 9001,
            "grademax": 5.0, "grademin": 0.0,
            "weight": None, "weight_override": False, "aggregationcoef2": None,
            "hidden": False, "locked": False, "idnumber": "", "calculation": "",
        },
        {
            "eid": "ig102", "item_id": GradeItemId(102), "parent_cat_id": GradeCategoryId(2),
            "name": "Asg 2", "kind": "assign", "cmid": 9002,
            "grademax": 5.0, "grademin": 0.0,
            "weight": None, "weight_override": False, "aggregationcoef2": None,
            "hidden": False, "locked": False, "idnumber": "", "calculation": "",
        },
    ]
    assignments_cat: GradeCategory = {
        "eid": "cg2", "cat_id": GradeCategoryId(2), "item_id": GradeItemId(200),
        "parent_cat_id": GradeCategoryId(1),
        "name": "Assignments", "aggregation": "sum",
        "droplow": 0, "keephigh": 0,
        "aggregateonlygraded": True, "aggregateoutcomes": False,
        "grademax": 10.0, "weight": None, "weight_override": False, "aggregationcoef2": None,
        "hidden": False, "idnumber": "",
        "items": asg_items, "subcategories": [],
    }
    bonus_item: GradeItem = {
        "eid": "ig103", "item_id": GradeItemId(103), "parent_cat_id": GradeCategoryId(1),
        "name": "Bonus", "kind": "manual", "cmid": None,
        "grademax": 7.0, "grademin": 0.0,
        "weight": None, "weight_override": False, "aggregationcoef2": None,
        "hidden": False, "locked": False, "idnumber": "", "calculation": "",
    }
    root: GradeCategory = {
        "eid": "cg1", "cat_id": GradeCategoryId(1), "item_id": GradeItemId(100),
        "parent_cat_id": None,
        "name": "CST9999", "aggregation": "sum",
        "droplow": 0, "keephigh": 0,
        "aggregateonlygraded": True, "aggregateoutcomes": False,
        "grademax": 100.0, "weight": None, "weight_override": False, "aggregationcoef2": None,
        "hidden": False, "idnumber": "",
        "items": [bonus_item], "subcategories": [assignments_cat],
    }
    return {"course_id": CourseId(999), "root": root}


class _FakeClient:
    def __init__(self, tree: GradeTree, *, cat_droplow: dict[int, int] | None = None,
                 item_idnumber: dict[int, str] | None = None,
                 item_calc: dict[int, str] | None = None) -> None:
        self._tree = tree
        self._cat_droplow = cat_droplow or {}
        self._item_idnumber = item_idnumber or {}
        self._item_calc = item_calc or {}

    def get_gradebook_tree(self, course_id: CourseId) -> GradeTree:  # noqa: ARG002
        return self._tree

    def get_grade_category_form(self, course_id: CourseId, cat_id: GradeCategoryId) -> dict[str, str]:  # noqa: ARG002
        return {
            "droplow": str(self._cat_droplow.get(int(cat_id), 0)),
            "keephigh": "0",
            "aggregateonlygraded": "1",
            "aggregateoutcomes": "0",
            "grade_item_idnumber": f"cat{int(cat_id)}id" if int(cat_id) == 2 else "",
            "grade_item_aggregationcoef2": "",
            "grade_item_aggregationcoef": "0",
            "grade_item_weightoverride": "0",
        }

    def get_grade_item_form(self, course_id: CourseId, item_id: GradeItemId) -> dict[str, str]:  # noqa: ARG002
        return {
            "idnumber": self._item_idnumber.get(int(item_id), ""),
            "aggregationcoef2": "",
            "aggregationcoef": "0",
            "weightoverride": "0",
            "locked": "0",
        }

    def get_grade_calculation(self, course_id: CourseId, item_id: GradeItemId) -> tuple[str, dict[GradeItemId, str]]:  # noqa: ARG002
        return self._item_calc.get(int(item_id), ""), {}


def test_render_tree_includes_all_nodes() -> None:
    client = _FakeClient(_build_tree())
    text = gradebook_feature.render_tree(client.get_gradebook_tree(CourseId(999)))
    assert "cg1" in text and "cg2" in text
    assert "ig101" in text and "ig102" in text and "ig103" in text
    assert "Bonus" in text
    # Indentation: subcategory deeper than root
    lines = text.splitlines()
    assert lines[0].startswith("[cg1]")
    assert any("  [cg2]" in line for line in lines)


def test_pull_serialises_structure_and_friendly_aggregation() -> None:
    tree = _build_tree()
    tree["root"]["subcategories"][0]["aggregation"] = "simple_weighted_mean"
    client = _FakeClient(
        tree,
        cat_droplow={2: 1},
        item_idnumber={103: "bonus"},
    )
    yaml_text = gradebook_feature.pull(client, CourseId(999))
    data: Any = yaml.safe_load(yaml_text)

    assert data["course_id"] == 999
    assert data["root"]["eid"] == "cg1"
    assert data["root"]["aggregation"] == "sum"

    children = data["root"]["children"]
    # subcategories serialised first (matches walk order in _category_to_yaml)
    asg = next(c["category"] for c in children if "category" in c)
    assert asg["eid"] == "cg2"
    assert asg["aggregation"] == "simple_weighted_mean"
    assert asg["droplow"] == 1
    assert asg["idnumber"] == "cat2id"
    assert len(asg["children"]) == 2

    bonus = next(c["item"] for c in children if "item" in c and c["item"]["eid"] == "ig103")
    assert bonus["kind"] == "manual"
    assert bonus["grademax"] == 7.0
    assert bonus["idnumber"] == "bonus"


def test_pull_marks_items_with_calculation_as_calculated() -> None:
    client = _FakeClient(
        _build_tree(),
        item_calc={103: "=[[bonus]]+1"},
    )
    yaml_text = gradebook_feature.pull(client, CourseId(999))
    data: Any = yaml.safe_load(yaml_text)
    bonus = next(
        c["item"]
        for c in data["root"]["children"]
        if "item" in c and c["item"]["eid"] == "ig103"
    )
    assert bonus["kind"] == "calculated"
    assert bonus["calculation"] == "=[[bonus]]+1"


def test_diff_idempotent_against_round_tripped_yaml() -> None:
    """Pulling YAML and diffing it back against the same live tree → no changes."""
    tree = _build_tree()
    client = _FakeClient(tree, cat_droplow={2: 1}, item_idnumber={103: "bonus"})
    yaml_text = gradebook_feature.pull(client, CourseId(999))
    changes = gradebook_feature.diff(client, CourseId(999), yaml_text, live_tree=client.get_gradebook_tree(CourseId(999)))
    # Re-enrich the live tree so the diff sees the same fields pull saw.
    # The simplest way: build a fresh client+tree and diff post-pull.
    # We re-enrich manually here mirroring the pull's enrichment.
    from moodlectl.features.gradebook import _enrich_tree, _walk_count
    fresh_tree = _build_tree()
    _enrich_tree(client, CourseId(999), fresh_tree["root"], None, [0], _walk_count(fresh_tree["root"]))
    changes = gradebook_feature.diff(client, CourseId(999), yaml_text, live_tree=fresh_tree)
    assert changes == []


def test_diff_detects_droplow_change() -> None:
    tree = _build_tree()
    from moodlectl.features.gradebook import _enrich_tree, _walk_count
    client = _FakeClient(tree, cat_droplow={2: 1})
    yaml_text = gradebook_feature.pull(client, CourseId(999))

    edited = yaml_text.replace("droplow: 1", "droplow: 2")
    fresh = _build_tree()
    _enrich_tree(client, CourseId(999), fresh["root"], None, [0], _walk_count(fresh["root"]))
    changes = gradebook_feature.diff(client, CourseId(999), edited, live_tree=fresh)
    assert len(changes) == 1
    ch = changes[0]
    assert ch.kind == "UPDATE_CATEGORY"
    assert ch.payload == {"droplow": "2"}
    assert ch.target_cat_id == 2


def test_diff_detects_new_manual_item_and_calculation() -> None:
    """Adding a manual item with a calculation emits CREATE_ITEM only (calc handled at create time)."""
    tree = _build_tree()
    from moodlectl.features.gradebook import _enrich_tree, _walk_count
    client = _FakeClient(tree)
    yaml_text = gradebook_feature.pull(client, CourseId(999))
    inserted = yaml_text.replace(
        "  - item:\n      eid: ig103\n      item_id: 103",
        ("  - item:\n      name: Bonus2\n      kind: manual\n      grademax: 7.0\n"
         "      idnumber: bonus2\n      calculation: '=[[bonus]]+1'\n"
         "  - item:\n      eid: ig103\n      item_id: 103"),
    )
    fresh = _build_tree()
    _enrich_tree(client, CourseId(999), fresh["root"], None, [0], _walk_count(fresh["root"]))
    changes = gradebook_feature.diff(client, CourseId(999), inserted, live_tree=fresh)
    create_items = [c for c in changes if c.kind == "CREATE_ITEM"]
    assert len(create_items) == 1
    payload = create_items[0].payload
    assert payload["itemname"] == "Bonus2"
    assert payload["itemtype"] == "manual"
    assert payload["grademax"] == "7.00"
    assert create_items[0].yaml_node.get("calculation") == "=[[bonus]]+1"


def test_push_executes_via_client(monkeypatch) -> None:
    """A simple UPDATE_CATEGORY change calls save_grade_category once with the payload."""
    calls: list[tuple[str, tuple, dict]] = []

    class _RecordingClient(_FakeClient):
        def save_grade_category(self, course_id, cat_id, changes, parent_cat_id=None):  # type: ignore[override]
            calls.append(("save_grade_category", (int(course_id), int(cat_id)), dict(changes)))
            return cat_id or 999

        def save_grade_item(self, course_id, item_id, changes, parent_cat_id=None):  # type: ignore[override]
            calls.append(("save_grade_item", (int(course_id), int(item_id)), dict(changes)))
            return item_id or 9999

        def save_grade_calculation(self, course_id, item_id, formula, idnumber_overrides=None):  # type: ignore[override]
            calls.append(("save_grade_calculation", (int(course_id), int(item_id)), {"formula": formula}))

    client = _RecordingClient(_build_tree())
    ch = gradebook_feature.Change(
        kind="UPDATE_CATEGORY",
        label="set droplow",
        payload={"droplow": "2"},
        target_cat_id=2,
    )
    failures = gradebook_feature.push(client, CourseId(999), [ch])
    assert failures == []
    assert calls == [("save_grade_category", (999, 2), {"droplow": "2"})]


def test_diff_two_pass_create_cat_with_child_moves() -> None:
    """Adding a subcategory + moving existing items into it should emit
    CREATE_CATEGORY + MOVE_ITEM(s) with pending_parent_tag wired up."""
    tree = _build_tree()
    from moodlectl.features.gradebook import _enrich_tree, _walk_count
    client = _FakeClient(tree)
    fresh = _build_tree()
    _enrich_tree(client, CourseId(999), fresh["root"], None, [0], _walk_count(fresh["root"]))

    edited_yaml = """\
course_id: 999
root:
  eid: cg1
  cat_id: 1
  item_id: 100
  name: CST9999
  aggregation: sum
  grademax: 100.0
  children:
    - category:
        # NO eid → CREATE
        name: New subcat
        aggregation: sum
        grademax: 5.0
        children:
          - item:
              eid: ig101
              item_id: 101
              name: Asg 1
              kind: assign
              grademax: 5.0
              cmid: 9001
    - item:
        eid: ig103
        item_id: 103
        name: Bonus
        kind: manual
        grademax: 7.0
"""
    changes = gradebook_feature.diff(client, CourseId(999), edited_yaml, live_tree=fresh)
    kinds = [c.kind for c in changes]
    assert "CREATE_CATEGORY" in kinds
    assert "MOVE_ITEM" in kinds
    # The CREATE has an own_tag; the MOVE points to that tag.
    create = next(c for c in changes if c.kind == "CREATE_CATEGORY")
    move = next(c for c in changes if c.kind == "MOVE_ITEM")
    assert create.own_tag != ""
    assert move.pending_parent_tag == create.own_tag
    assert move.target_parent_cat_id == 0


def _set_node(parsed: dict, item_id: int, **kwargs: object) -> None:
    """Recursively find an item by item_id in a parsed YAML dict and merge kwargs."""
    for c in parsed.get("children", []) or []:
        if "item" in c and c["item"].get("item_id") == item_id:
            c["item"].update(kwargs)
            return
        if "category" in c:
            _set_node(c["category"], item_id, **kwargs)


def test_diff_emits_via_calc_form_for_activity_idnumber() -> None:
    """idnumber update on an activity-backed item should emit a separate
    UPDATE_ITEM with via_calc_form=True (item.php silently ignores idnumber)."""
    from moodlectl.features.gradebook import _enrich_tree, _walk_count
    tree = _build_tree()
    client = _FakeClient(tree)
    fresh = _build_tree()
    _enrich_tree(client, CourseId(999), fresh["root"], None, [0], _walk_count(fresh["root"]))
    yaml_text = gradebook_feature.pull(client, CourseId(999))
    parsed = yaml.safe_load(yaml_text)
    _set_node(parsed["root"], 101, idnumber="a1")  # ig101 is activity-backed (cmid=9001)
    edited = yaml.safe_dump(parsed)
    changes = gradebook_feature.diff(client, CourseId(999), edited, live_tree=fresh)
    calc_form_changes = [c for c in changes if c.kind == "UPDATE_ITEM" and c.via_calc_form]
    assert len(calc_form_changes) == 1
    assert calc_form_changes[0].payload == {"idnumber": "a1"}
    assert calc_form_changes[0].target_item_id == 101


def test_diff_emits_delete_item_for_missing_activity_item() -> None:
    """When an activity item disappears from YAML, diff emits DELETE_ITEM with cmid."""
    from moodlectl.features.gradebook import _enrich_tree, _walk_count
    tree = _build_tree()
    client = _FakeClient(tree)
    fresh = _build_tree()
    _enrich_tree(client, CourseId(999), fresh["root"], None, [0], _walk_count(fresh["root"]))
    yaml_text = gradebook_feature.pull(client, CourseId(999))
    # Drop ig102 (activity, cmid=9002) from YAML
    parsed = yaml.safe_load(yaml_text)
    def _drop(node: dict, item_id: int) -> None:
        kids = node.get("children") or []
        node["children"] = [
            c for c in kids
            if not (c.get("item") and c["item"].get("item_id") == item_id)
        ]
        for c in node["children"]:
            if "category" in c:
                _drop(c["category"], item_id)
    _drop(parsed["root"], 102)
    edited = yaml.safe_dump(parsed)
    changes = gradebook_feature.diff(client, CourseId(999), edited, live_tree=fresh)
    deletes = [c for c in changes if c.kind == "DELETE_ITEM"]
    assert len(deletes) == 1
    assert deletes[0].target_item_id == 102
    assert deletes[0].payload == {"cmid": "9002"}


def test_diff_no_delete_for_missing_manual_item() -> None:
    """Manual items missing from YAML should NOT emit DELETE_ITEM (Moodle web can't)."""
    from moodlectl.features.gradebook import _enrich_tree, _walk_count
    tree = _build_tree()
    client = _FakeClient(tree)
    fresh = _build_tree()
    _enrich_tree(client, CourseId(999), fresh["root"], None, [0], _walk_count(fresh["root"]))
    yaml_text = gradebook_feature.pull(client, CourseId(999))
    parsed = yaml.safe_load(yaml_text)
    parsed["root"]["children"] = [
        c for c in (parsed["root"].get("children") or [])
        if not (c.get("item") and c["item"].get("item_id") == 103)
    ]
    edited = yaml.safe_dump(parsed)
    changes = gradebook_feature.diff(client, CourseId(999), edited, live_tree=fresh)
    assert [c for c in changes if c.kind == "DELETE_ITEM"] == []


def test_diff_emits_set_module_visible_when_yaml_hides_activity() -> None:
    """Setting module_visible: false in YAML emits SET_MODULE_VISIBLE."""
    from moodlectl.features.gradebook import _enrich_tree, _walk_count
    tree = _build_tree()
    client = _FakeClient(tree)
    fresh = _build_tree()
    _enrich_tree(client, CourseId(999), fresh["root"], None, [0], _walk_count(fresh["root"]))
    # Mark ig101 module visible=True in live (simulate the pull result)
    for it in fresh["root"]["subcategories"][0]["items"]:
        if it["item_id"] == 101:
            it["module_visible"] = True
    yaml_text = gradebook_feature.pull(client, CourseId(999))
    parsed = yaml.safe_load(yaml_text)
    _set_node(parsed["root"], 101, module_visible=False)
    edited = yaml.safe_dump(parsed)
    changes = gradebook_feature.diff(client, CourseId(999), edited, live_tree=fresh)
    hides = [c for c in changes if c.kind == "SET_MODULE_VISIBLE"]
    assert len(hides) == 1
    assert hides[0].payload == {"cmid": "9001", "visible": "0"}


def test_push_resolves_pending_parent_tag_for_moves() -> None:
    """End-to-end: push handles CREATE_CATEGORY + MOVE_ITEM that depend on the new cat_id."""
    calls: list[tuple[str, tuple, dict]] = []

    class _RecordingClient(_FakeClient):
        def __init__(self) -> None:
            super().__init__(_build_tree())
            self._new_cat_id = 555

        def save_grade_category(self, course_id, cat_id, changes, parent_cat_id=None):  # type: ignore[override]
            calls.append(("save_grade_category", (int(course_id), int(cat_id), int(parent_cat_id or 0)), dict(changes)))
            if cat_id == 0:
                return self._new_cat_id  # newly created cat
            return cat_id

        def move_grade_item(self, course_id, item_eid, target_eid, first=True):  # type: ignore[override]
            calls.append(("move_grade_item", (int(course_id), item_eid, target_eid), {"first": first}))

        def get_gradebook_tree(self, course_id):  # type: ignore[override]
            # Return a tree where the new cat lives under cg1
            tree = _build_tree()
            from moodlectl.types import GradeCategory, GradeCategoryId, GradeItemId
            new_cat: GradeCategory = {
                "eid": f"cg{self._new_cat_id}", "cat_id": GradeCategoryId(self._new_cat_id),
                "item_id": GradeItemId(7000), "parent_cat_id": GradeCategoryId(1),
                "name": "New subcat", "aggregation": "sum",
                "droplow": 0, "keephigh": 0, "aggregateonlygraded": True, "aggregateoutcomes": False,
                "grademax": 5.0, "weight": None, "weight_override": False, "aggregationcoef2": None,
                "hidden": False, "idnumber": "",
                "items": [], "subcategories": [],
            }
            tree["root"]["subcategories"].append(new_cat)
            return tree

    client = _RecordingClient()
    create = gradebook_feature.Change(
        kind="CREATE_CATEGORY", label="create",
        payload={"fullname": "New subcat", "aggregation": "13"},
        parent_cat_id=1, own_tag="__tag_x__",
    )
    move = gradebook_feature.Change(
        kind="MOVE_ITEM", label="move",
        target_eid="ig101", target_item_id=101,
        target_parent_cat_id=0, pending_parent_tag="__tag_x__",
    )
    failures = gradebook_feature.push(client, CourseId(999), [create, move])
    assert failures == []
    # The move was issued to cg555 (the newly created cat id)
    move_call = next(c for c in calls if c[0] == "move_grade_item")
    assert move_call[1] == (999, "ig101", "cg555")


def test_pull_progress_callback_fires_for_every_node() -> None:
    seen: list[tuple[int, int, str]] = []

    def cb(current: int, total: int, name: str) -> None:
        seen.append((current, total, name))

    client = _FakeClient(_build_tree())
    gradebook_feature.pull(client, CourseId(999), progress=cb)
    # 2 categories + 3 items = 5 calls
    assert len(seen) == 5
    # Final call should reach the total
    assert seen[-1][0] == seen[-1][1] == 5

# -*- coding: utf-8 -*-
"""A task on a group can be opened, changed and saved again.

THE FINDING (independent review, 2026-09-23): the ADD form offers groups, the
EDIT modal does not - its container select is rendered from the containers
alone. Opening a group task therefore selects nothing (a select set to a value
with no option ends up empty), and:

* saving fails with "please fill in the required fields" - the task can never
  be edited, only deleted and made again;
* or, if the operator works around it by picking a container from the list,
  the form does not send target_is_group, the service keeps the old flag on
  purpose, and the task ends up as a GROUP task pointing at a container name.
  Every run then reports "The group 'plex' does not exist any more" - for ever.

So the edit modal offers the groups too, and it sends which kind of target was
chosen, exactly as the add form does.

COUNTER-CHECK (2026-09-23): red before - editTaskContainer appeared in no
group code at all, and collectFormData sent no target_is_group.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "app" / "static" / "js" / "tasks.js").read_text(encoding="utf-8")
# The edit dialog moved to its own partial on 2026-09-23: it lived at the end
# of list.html, which config.html includes INSIDE <form id="config-form">, so
# its own <form id="editTaskForm"> was a form inside a form - which a browser
# throws away. It sits beside the other modals now, outside that form.
LIST = (ROOT / "app" / "templates" / "tasks" / "_edit_modal.html").read_text(encoding="utf-8")


def test_the_edit_modal_has_a_place_for_the_groups():
    assert "edit-target-group" in LIST, "the edit modal cannot show a group at all"


def test_the_groups_are_filled_in_before_the_task_is():
    """A select cannot hold a value whose option does not exist yet."""
    assert "edit-target-group" in JS, "the edit modal's group list is never filled"
    filling = JS.split("populateEditForm")[1][:600]

    assert "fillEditGroups" in filling or "edit-target-group" in filling, (
        "the task is put into the form before the group options exist")


def test_the_edit_sends_which_kind_of_target_it_is():
    collected = JS.split("collectFormData() {")[1][:1600]

    assert "target_is_group" in collected, (
        "an edited group task keeps the flag while pointing at a container")


def test_the_update_route_passes_it_on():
    routes = (ROOT / "app" / "blueprints" / "tasks_bp.py").read_text(encoding="utf-8")

    assert "target_is_group" in routes, "the flag does not survive the route"

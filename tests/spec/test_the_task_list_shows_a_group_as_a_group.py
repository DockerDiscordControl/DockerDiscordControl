# -*- coding: utf-8 -*-
"""A task on a group looks like one in the list.

A task can target a group (test_a_task_can_target_a_group.py) and the form can
pick one (test_the_task_form_offers_groups.py). In the list it then sat there
as a plain name in the container column - indistinguishable from a container
of that name, which is exactly the confusion the flag exists to prevent. An
operator reading "Gameserver · restart · weekly" has no way to tell whether
that restarts five containers or one.

The row marks it, and says how many containers are in it at the moment.

COUNTER-CHECK (2026-09-23): red before - tasks.js knew nothing about
target_is_group, and the list route did not even carry it.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "app" / "static" / "js" / "tasks.js").read_text(encoding="utf-8")


def test_the_row_knows_a_group_when_it_sees_one():
    assert "target_is_group" in JS, "the list cannot tell a group from a container"


def test_the_group_is_marked_not_just_named():
    """A different colour or icon - a name alone is what caused the confusion."""
    marked = JS.split("target_is_group")[1][:400]

    assert "bi-collection" in marked or "text-warning" in marked, (
        "a group is drawn exactly like a container")


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_word_for_it_exists(language):
    catalogue = json.loads((ROOT / "locales" / f"{language}.json").read_text(encoding="utf-8"))

    assert catalogue.get("js.tasks.group_badge"), f"{language}.json has no word for it"


def test_the_list_route_carries_the_flag():
    """The mark is worth nothing if the data never reaches the page."""
    service = (ROOT / "services" / "web" / "task_management_service.py").read_text(encoding="utf-8")

    assert "target_is_group" in service.split("def _process_task_for_frontend")[1][:1500], (
        "the row is built from data that does not say whether this is a group")

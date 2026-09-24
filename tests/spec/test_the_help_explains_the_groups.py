# -*- coding: utf-8 -*-
"""The help says what a group is, in both places help is offered.

THE OPERATOR, 2026-09-24, reading his own help text: it lists the commands,
the status lamps, the buttons and the admin panel - and says nothing at all
about container groups, which now stand in the overview, are picked in the
admin list and are acted on like a container.

AND ONE LAMP MEANS TWO THINGS NOW. 🟡 on a container line is "an action is
running"; on a group line it is "some of its containers are up". The count
beside it says which - "🟡 Icaruse 1/2" cannot be an action - but a help text
that explains the first and not the second leaves the operator to work that
out.

THERE ARE TWO HELPS, and they are not copies: `/help` (cogs/slash_commands.py)
documents the channel commands, the info system and the task scheduling; the
❓ button (cogs/control_ui.py) documents the overview it sits under. They have
drifted - only one of them explained 🟡 at all - and merging them is a decision
for the operator, not a side effect of this change. So both get the group
section, and the one that never explained 🟡 gets that too.

THE SECTION ITSELF IS WRITTEN ONCE (cogs/group_control.py group_help_field):
two helps that each build their own copy is how they drifted in the first
place. So this file checks that both CALL it, and checks the sentences where
they now live.

HOW THIS TEST CAN FAIL: a help that forgets the groups, or one of the two
falling behind the other again.

COUNTER-CHECK (2026-09-24): red before - neither help contained the word.
"""

import ast
import json
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
HELPS = ("cogs/control_ui.py", "cogs/slash_commands.py")

# The texts the group section is built from. Each is a catalogue key, so each
# is a sentence somebody can translate.
GROUP_TEXTS = (
    "A group acts like a single container, with permissions of its own",
    "all of its containers are running",
    "some are running",
    "none is running",
    "Pick one in the Admin panel to control all its containers at once",
)


def _literals(relative):
    """Every translated literal in that file, whatever the function is called."""
    source = (PROJECT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"_"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and "translation" in (node.module or ""):
            for alias in node.names:
                if alias.name in ("_", "translate"):
                    names.add(alias.asname or alias.name)
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in names and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            found.add(node.args[0].value)
    return found


@pytest.mark.parametrize("relative", HELPS)
def test_both_helps_show_the_group_section(relative):
    """THE GAP: neither said the word - and now both ask the same writer."""
    tree = ast.parse((PROJECT / relative).read_text(encoding="utf-8"))
    calls = [ast.unparse(node.func) for node in ast.walk(tree)
             if isinstance(node, ast.Call)]

    assert any("group_help_field" in call for call in calls), (
        f"{relative} shows no group section")


def test_the_section_says_what_a_group_is():
    """The sentences, where they are written."""
    literals = _literals("cogs/group_control.py")

    assert "Container groups" in literals
    missing = [text for text in GROUP_TEXTS if text not in literals]

    assert missing == [], f"the group section is missing: {missing}"


@pytest.mark.parametrize("relative", HELPS)
def test_both_helps_explain_the_pending_lamp(relative):
    """One of them never did, and it is the lamp that now means two things."""
    literals = _literals(relative)

    assert "Action pending (starting/stopping)" in literals, (
        f"{relative} shows 🟡 in the overview and never says what it is")


def test_the_group_section_carries_the_folder_and_the_lamps():
    """The section is read beside the overview it describes, so it uses the
    same marks: the folder that marks a group in a list, and the three lamps
    that stand in its line. Rendered, not read from the source - a mark in a
    comment would satisfy a search of the text."""
    from cogs.group_control import group_help_field

    name, value = group_help_field()

    assert "Container groups" in name
    for mark in ("📁", "🟢", "🟡", "🔴"):
        assert mark in value, f"the group section has no {mark}"


@pytest.mark.parametrize("text", GROUP_TEXTS)
def test_every_new_sentence_is_in_every_catalogue(text):
    """A bot string that is not a key falls back to English for every server."""
    missing = []
    for path in sorted((PROJECT / "locales").glob("*.json")):
        if path.name == "meta.json":
            continue
        if text not in json.loads(path.read_text(encoding="utf-8")):
            missing.append(path.name)

    assert missing == [], f"{text!r} is missing from {len(missing)} catalogues: {missing[:5]}"


def test_the_german_ones_are_really_german():
    """A key copied in with the English text still in it is how this has gone
    wrong before: present, formatted, and not German."""
    german = json.loads((PROJECT / "locales" / "de.json").read_text(encoding="utf-8"))
    same = [text for text in GROUP_TEXTS if german.get(text) == text]

    assert same == [], f"these are still the English texts: {same}"

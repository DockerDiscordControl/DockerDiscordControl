# -*- coding: utf-8 -*-
"""A button registered to survive a restart must be on a message DDC posts.

WHAT ``bot.add_view`` IS FOR. Discord keeps a message's buttons long after
the process that sent them is gone. ``add_view`` hands py-cord a view whose
custom_ids match those old buttons, so a press on a message from before the
restart still finds a handler. It posts nothing.

THE FINDING. ``MechExpandButton`` and ``MechCollapseButton`` were registered
that way and carried by no posted view. They are the old shape of the status
channel overview: the public message itself swapped to a version with the big
mech in place, switched by a pair of buttons. Today that message carries
``MechView`` - Mech, info, admin, help - and the big mech lives in the private
panel the Mech button opens (``MechDetailsView``).

The operator said so twice, the second time with screenshots, before this test
existed. Measured afterwards:

    MechView                 AdminButton, HelpButton, InfoDropdownButton,
                             MechDetailsButton - no expand, no collapse
    config/mech_state.json   one channel, false, last written 2026-09-16
    ten months of logs       mech_expand, mech_collapse: zero lines
    user_actions.json        no mech action at all

WHY THE RULE IS WORTH KEEPING. A registration for a button nobody can press
is not harmless: it is a statement that such messages exist. It kept 402
lines of a second overview builder alive behind it, and three comments
claiming ``MechView`` has expand and collapse buttons.

THE MISTAKE THIS SCAN ALMOST MADE, written down because it is the eleventh of
its kind today: the first version looked for ``add_item(SomeButton(...))``
and reported six unreachable buttons. Four of them were wrong -
``MechDisplayButton``, ``EpilogueButton``, ``MechDonateButton`` and
``MechHistoryButton`` are attached through a VARIABLE::

    button = MechDisplayButton(...)
    self.add_item(button)

so the scan asks which button classes are CONSTRUCTED inside a view, not how
they reach ``add_item``. Deleting on the first answer would have taken four
live controls off the operator's panels.

HOW THIS TEST CAN FAIL: a button class that only ever appears in a view
handed to ``bot.add_view`` and on no view DDC posts.

COUNTER-CHECK (2026-09-25): red before - MechExpandButton and
MechCollapseButton, each in its own persistent view.
"""

import ast
import collections
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
PRESSABLE = ("Button", "Select")


def _trees():
    for path in sorted((PROJECT / "cogs").glob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"))


def _button_classes(trees):
    names = set()
    for _path, tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                    ast.unparse(base).split(".")[-1] in PRESSABLE for base in node.bases):
                names.add(node.name)
    return names


def _enclosing_class(tree):
    parent = {}

    def walk(node):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
            walk(child)

    walk(tree)

    def up(node):
        while node is not None and not isinstance(node, ast.ClassDef):
            node = parent.get(node)
        return node

    return up


def _map(trees, buttons):
    """(view class -> buttons it builds, and where each view is constructed)."""
    builds = collections.defaultdict(set)
    inside, outside = collections.defaultdict(list), collections.defaultdict(list)

    for path, tree in trees:
        up = _enclosing_class(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in buttons:
                owner = up(node)
                if owner is not None:
                    builds[owner.name].add(node.func.id)

    for path, tree in trees:
        registered = set()
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "add_view"):
                continue
            for sub in ast.walk(call):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    registered.add((sub.lineno, sub.col_offset, sub.func.id))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in builds:
                seat = (node.lineno, node.col_offset, node.func.id)
                target = inside if seat in registered else outside
                target[node.func.id].append(f"{path.name}:{node.lineno}")

    return builds, inside, outside


def _unreachable(trees):
    buttons = _button_classes(trees)
    builds, inside, outside = _map(trees, buttons)

    posted, registered_only = set(), collections.defaultdict(list)
    for view, made in builds.items():
        if view in outside:
            posted |= made
        elif view in inside:
            for button in made:
                registered_only[button].append(view)

    found = sorted(f"{button} (only in {', '.join(sorted(views))})"
                   for button, views in registered_only.items() if button not in posted)
    return found, registered_only, posted


def test_no_button_is_registered_for_a_message_nothing_posts():
    """THE FINDING: the old overview's expand and collapse pair."""
    found, _registered, _posted = _unreachable(list(_trees()))

    assert found == [], (
        "these buttons only exist as handlers for messages DDC no longer "
        f"sends: {found}")


def test_the_scan_has_something_to_look_at():
    """The counter-check eleven sabotages have walked past: a scan with no
    subjects passes the case above while proving nothing.

    DDC really does register persistent views, and the buttons on them really
    are also on posted views - that is what the registration is for."""
    _found, registered_only, posted = _unreachable(list(_trees()))

    assert len(registered_only) >= 4, sorted(registered_only)
    assert set(registered_only) <= posted, (
        "the case above is not vacuous only while this holds")


def test_a_button_attached_through_a_variable_still_counts():
    """THE MISTAKE THIS SCAN ALMOST MADE. Four live controls are attached by
    name, not inline, and a scan reading only ``add_item(X(...))`` called
    them dead."""
    source = (
        "class Holder(DDCView):\n"
        "    def __init__(self, cog):\n"
        "        button = Lever(cog)\n"
        "        self.add_item(button)\n"
        "\n"
        "class Lever(Button):\n"
        "    pass\n")
    trees = [(Path("made_up.py"), ast.parse(source))]
    buttons = _button_classes(trees)
    builds, _inside, _outside = _map(trees, buttons)

    assert "Lever" in buttons
    assert builds["Holder"] == {"Lever"}, builds


def test_a_button_on_no_view_at_all_is_a_different_question():
    """The opposite mistake. This rule is about a REGISTRATION that outlived
    its message. A class nobody builds anywhere is dead in a plainer way and
    belongs to the helper scan, not here - claiming it would make this test
    fire for reasons its name does not describe."""
    source = (
        "class Orphan(Button):\n"
        "    pass\n")
    found, _registered, _posted = _unreachable([(Path("made_up.py"), ast.parse(source))])

    assert found == [], found

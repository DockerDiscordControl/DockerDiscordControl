# -*- coding: utf-8 -*-
"""A panel only you can see offers a way to take it away.

THE OPERATOR, 2026-09-25, on the Mech panel: "there is no close button here -
everywhere there are buttons, the closing X has to be there."

THE ONE HE SAW WAS NOT THE ONLY ONE. The close button was given to the admin
panel the day before, by the factory that builds it. Measured across the tree,
twelve further views are delivered ONLY as ephemeral messages and carried no
way out at all - the mech details, the mech gallery and its stories, the
container info panels, the task views, the password prompt.

HIS OTHER RULE STILL HOLDS, and it is the one that makes this checkable in
both directions: the status and control channel overviews must NEVER carry
it. A close button on a message everybody reads would let any reader delete
it for all of them. So the rule is not "every view" - it is every view that
is only ever sent to one person.

WHAT COUNTS AS A WAY OUT. The close button, or an explicit cancel. The bulk
confirmations and the stack picker already end in "Cancel", which both
refuses the action and dismisses the message; giving those a second control
that only dismisses would offer two exits with different meanings.

HOW PRIVACY IS DECIDED - from the tree, not from a list. A view is private
when it is handed to a send with ``ephemeral=True`` and never to one without.
``edit_*`` calls say nothing either way: editing an ephemeral message keeps it
ephemeral, so they are not counted in either direction, and a view that is
ONLY ever edited into place is named below rather than guessed at.

WHERE THE BUTTON SITS is left to py-cord: it is added last with no row, and
the layout engine puts it in the first row with space. Measured against
``to_components()``, which is what Discord actually receives:

    three action buttons  -> [b0 b1 b2 ✕]        one row, as he asked
    a dropdown            -> [select] [✕]        its own row underneath
    twelve buttons        -> [.....][.....][.. ✕]

HOW THIS TEST CAN FAIL: a private view with buttons and no way out, or a
close button on a view that is ever sent publicly.

COUNTER-CHECK (2026-09-25): red before, naming all twelve.
"""

import ast
import collections
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
COGS = PROJECT / "cogs"

SENDS = ("send_message", "send", "respond")
EDITS = ("edit_original_response", "edit_message", "edit")
A_WAY_OUT = ("CloseButton", "CancelBulkActionButton")


def _trees():
    return {path: ast.parse(path.read_text(encoding="utf-8"))
            for path in sorted(COGS.glob("*.py"))}


def _parents(tree):
    parent = {}

    def walk(node):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
            walk(child)

    walk(tree)
    return parent


def _controls_and_exits(trees):
    """(view -> does it carry controls, view -> the exits it builds).

    TWO SPELLINGS TRIPPED THE FIRST VERSION, both of them the same lesson as
    the rest of the day: StackPickView builds its cancel as
    ``ao.CancelBulkActionButton(...)`` - an attribute, not a bare name - and
    LiveLogView builds plain ``discord.ui.Button`` objects rather than
    classes of its own, so a scan looking only for named Button subclasses
    thought it had no controls at all. It has two, and a comment promising a
    third.

    So "carries controls" is asked of ``add_item`` itself, and an exit is
    recognised by the LAST part of whatever is called.
    """
    carries = collections.defaultdict(bool)
    exits = collections.defaultdict(set)
    for _path, tree in trees.items():
        parent = _parents(tree)
        # A PrivateView gets its way out from the type (cogs/ddc_ui.py), which
        # is how six views inside control_ui.py could be given one without
        # growing a file that is on the size ceiling.
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                    ast.unparse(b).split(".")[-1] == "PrivateView" for b in node.bases):
                exits[node.name].add("PrivateView")

        def owner_of(node):
            while node is not None and not isinstance(node, ast.ClassDef):
                node = parent.get(node)
            return node

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = ast.unparse(node.func).split(".")[-1]
            owner = owner_of(node)
            if owner is None:
                continue
            if called == "add_item":
                carries[owner.name] = True
            if called in A_WAY_OUT:
                exits[owner.name].add(called)
    return carries, exits


def _adds_a_close_button_always(trees, view):
    """Whether this view builds a close button no matter what it was told.

    THE DISTINCTION MATTERS FOR ONE VIEW. DonationView is sent twice
    privately and once, from /donate, publicly. It takes ``private`` and adds
    the button only under it, which is right: a close button on the public
    one would sit there refusing every press, since it asks the message's own
    ephemeral flag first. A rule that forbade a public view from MENTIONING
    the button would forbid that pattern too - which the first version did,
    and it went red on the very change that fixed the finding.
    """
    for _path, tree in trees.items():
        parent = _parents(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and ast.unparse(node.func).split(".")[-1] == "CloseButton"):
                continue
            owner, guarded = node, False
            while owner is not None and not isinstance(owner, ast.ClassDef):
                if isinstance(owner, ast.If) and "private" in ast.unparse(owner.test):
                    guarded = True
                owner = parent.get(owner)
            if owner is not None and owner.name == view and not guarded:
                return True
    return False


def _how_each_view_is_delivered(trees):
    """view class -> {'private', 'public'}; edits are counted as neither."""
    delivery = collections.defaultdict(set)
    for _path, tree in trees.items():
        parent = _parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = ast.unparse(node.func).split(".")[-1]
            if called not in SENDS + EDITS:
                continue
            handed = next((k.value for k in node.keywords if k.arg == "view"), None)
            if handed is None:
                continue

            names = set()
            if isinstance(handed, ast.Call) and isinstance(handed.func, ast.Name):
                names.add(handed.func.id)
            elif isinstance(handed, ast.Name):
                enclosing = node
                while enclosing is not None and not isinstance(
                        enclosing, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    enclosing = parent.get(enclosing)
                if enclosing is not None:
                    for step in ast.walk(enclosing):
                        if (isinstance(step, ast.Assign)
                                and any(isinstance(t, ast.Name) and t.id == handed.id
                                        for t in step.targets)
                                and isinstance(step.value, ast.Call)
                                and isinstance(step.value.func, ast.Name)):
                            names.add(step.value.func.id)

            private = any(k.arg == "ephemeral" and getattr(k.value, "value", None) is True
                          for k in node.keywords)
            for name in names:
                if private:
                    delivery[name].add("private")
                elif called in SENDS:
                    delivery[name].add("public")
    return delivery


# Delivered ONLY by editing a message already on screen, so the send tells
# nothing. Measured by hand on 2026-09-25 and written down rather than left to
# a guess: InfoButton edits the message it sits on, and the only view carrying
# an InfoButton is the ephemeral admin panel.
ONLY_EVER_EDITED_INTO_PLACE = {"PasswordProtectedView": "private"}


def _private_views(trees):
    delivery = _how_each_view_is_delivered(trees)
    private = {name for name, how in delivery.items()
               if "private" in how and "public" not in how}
    private |= {name for name, how in ONLY_EVER_EDITED_INTO_PLACE.items() if how == "private"}
    return private


def _ephemeral_sends(trees):
    """(where, view class, was it built asking for a way out) per private send.

    ASKED OF THE SEND, NOT OF THE CLASS - because the first version asked of
    the class and let the donation panel through. DonationView goes out THREE
    times: twice with ephemeral=True and once, from /donate, publicly with an
    auto-delete timer. A rule about classes that are "only ever private" skips
    a class that is sometimes private, which is exactly the one that needs
    telling apart at the send.
    """
    for path, tree in trees.items():
        parent = _parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if ast.unparse(node.func).split(".")[-1] not in SENDS:
                continue
            if not any(k.arg == "ephemeral" and getattr(k.value, "value", None) is True
                       for k in node.keywords):
                continue
            handed = next((k.value for k in node.keywords if k.arg == "view"), None)
            if handed is None or (isinstance(handed, ast.Constant) and handed.value is None):
                continue

            built = handed if isinstance(handed, ast.Call) else None
            if isinstance(handed, ast.Name):
                enclosing = node
                while enclosing is not None and not isinstance(
                        enclosing, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    enclosing = parent.get(enclosing)
                if enclosing is not None:
                    for step in ast.walk(enclosing):
                        if (isinstance(step, ast.Assign)
                                and any(isinstance(x, ast.Name) and x.id == handed.id
                                        for x in step.targets)
                                and isinstance(step.value, ast.Call)):
                            built = step.value
            if built is None or not isinstance(built.func, ast.Name):
                continue
            asked = any(k.arg == "private" and getattr(k.value, "value", None) is True
                        for k in built.keywords)
            yield f"{path.name}:{node.lineno}", built.func.id, asked


def test_every_private_panel_offers_a_way_out():
    """THE FINDING: twelve panels only one person can see, none of which
    could be taken away - and a thirteenth the first rule walked past."""
    trees = _trees()
    carries, exits = _controls_and_exits(trees)

    stranded = sorted(name for name in _private_views(trees)
                      if carries.get(name) and not exits.get(name))

    assert stranded == [], (
        "these are sent to one person, carry buttons, and offer no way to "
        f"take them away: {stranded}")

    # and the same question asked of every ephemeral send, which catches a
    # view that is private HERE and public somewhere else
    mixed = sorted(f"{where} ({view})" for where, view, asked in _ephemeral_sends(trees)
                   if carries.get(view) and not exits.get(view) and not asked)

    assert mixed == [], (
        "these send a panel to one person with no way to take it away: "
        f"{mixed}")


def test_the_public_overviews_still_carry_none():
    """HIS WARNING, as a running check. A close button on a message the whole
    channel reads would let any reader delete it for everybody."""
    trees = _trees()
    delivery = _how_each_view_is_delivered(trees)
    public = {name for name, how in delivery.items() if "public" in how}

    offenders = sorted(name for name in public if _adds_a_close_button_always(trees, name))

    assert offenders == [], (
        f"a view that is sent publicly carries a close button: {offenders}")

    # and the two that matter are really in that set, or the case is empty
    assert {"MechView", "AdminOverviewView"} <= public, sorted(public)


def test_an_unguarded_close_button_on_a_public_view_is_still_caught():
    """The counter-check on the refinement above: loosening the public rule
    must not loosen it away. A close button added unconditionally in a view
    the channel can see is the thing he forbade."""
    sabotage = ast.parse(
        "class Loud(DDCView):\n"
        "    def __init__(self):\n"
        "        self.add_item(CloseButton())\n")
    careful = ast.parse(
        "class Quiet(DDCView):\n"
        "    def __init__(self, private=False):\n"
        "        if private:\n"
        "            self.add_item(CloseButton())\n")

    assert _adds_a_close_button_always({Path("made_up.py"): sabotage}, "Loud")
    assert not _adds_a_close_button_always({Path("made_up.py"): careful}, "Quiet")


def test_the_scan_knows_which_views_are_private():
    """The counter-check eleven sabotages have walked past: an empty subject
    set passes both cases above while proving nothing."""
    trees = _trees()
    private = _private_views(trees)

    assert len(private) >= 10, sorted(private)
    assert "MechDetailsView" in private, sorted(private)
    assert "MechView" not in private, "the channel overview is not a private panel"


def test_the_type_really_hands_the_button_over():
    """The base class is a NAME, and a name proves nothing - this is the
    eleventh time today a scan of mine had to be turned from a word into a
    behaviour. So two real views are built and asked what they carry.

    MechDetailsView is the one the operator photographed; MechSelectionView
    is the awkward case, because its buttons already fill rows and the X has
    to find a seat by itself."""
    import asyncio

    from types import SimpleNamespace

    from cogs.control_ui import MechDetailsView, MechSelectionView

    async def build():
        cog = SimpleNamespace(pending_actions={})
        return (MechDetailsView(cog, 4242).to_components(),
                MechSelectionView(cog, 11).to_components())

    details, gallery = asyncio.run(build())

    def last_of(rendered):
        return rendered[-1]["components"][-1].get("custom_id")

    assert last_of(details) == "ddc_close_panel", details
    assert last_of(gallery) == "ddc_close_panel", gallery

    # and it is the LAST control, not one that pushed the others aside
    first_row = [c.get("custom_id") for c in details[0]["components"]]

    assert first_row[:2] == ["mech_private_donate_4242", "mech_private_history_4242"], first_row


def test_a_cancel_counts_as_a_way_out():
    """The opposite mistake. The bulk confirmations end in Cancel, which
    refuses the action AND dismisses the message. Demanding a second control
    there would offer two exits that mean different things."""
    trees = _trees()
    _carries, exits = _controls_and_exits(trees)

    for confirmation in ("RestartAllConfirmationView", "StopAllConfirmationView",
                         "StackPickView"):
        assert "CancelBulkActionButton" in exits[confirmation], exits[confirmation]
        assert "CloseButton" not in exits[confirmation], exits[confirmation]

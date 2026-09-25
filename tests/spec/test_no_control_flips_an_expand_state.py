# -*- coding: utf-8 -*-
"""No button expands or collapses a container, because that panel is gone.

THE FINDING. ``ToggleButton`` - the ➕/➖ control that expanded a container's
status into its action buttons - could not be pressed by anybody. It was added
in exactly one place, ``ControlView.__init__`` under ``allow_toggle``, and
every live caller passed ``False``:

    cogs/group_control.py:276   allow_toggle=False   the admin panel's embed
    cogs/group_control.py:310   allow_toggle=False   the admin panel's view

The one remaining ``allow_toggle=True`` sat in ``ActionButton.callback``, in
the branch taken when the pressed message is NOT a private panel. Every view
that carries an ``ActionButton`` is built by ``admin_control_view()``, which
Discord delivers as an ephemeral followup, and ``is_private_panel_message()``
answers "private" for exactly that. So the branch was the error fallback, not
a second way in, and the button it would have produced never reached anyone.

MEASURED, because a proof by reading is how I got this wrong once already:

    logs/user_actions.json   2026-04-26 .. 2026-09-25, 47 presses on a
                             Discord button - every one start, stop or
                             restart, not one expand or collapse
    logs/*.log               ten months, zero lines naming the toggle

THE OPERATOR SAID SO FIRST. Shown the line that added it, he answered that
there is no expanding here, that it was a thing "a very long time ago". He was
right and I was reading dead code as live - and then told him something false
about his own panel.

WHAT THE RULE IS. An expand state is now set by whoever OPENS a panel, to the
one value that panel needs: the admin dropdown sets it True before drawing,
the mech's two buttons each set their own constant. Nothing FLIPS one any
more, because flipping was the toggle's job. So: a control - a Button or a
Select the operator can press - must not assign a computed value into an
``expanded_states`` map. A constant is a panel stating what it shows; a
computed value is a toggle.

DELIBERATELY LEFT, so the question is not lost: with the toggle gone,
``expanded_states`` only ever holds True where it is read (cogs/control_ui.py
:1040), because both writers set True. The ``is_expanded`` gate below it is
therefore constant as well. That is a second removal with its own proof to
do, and bundling it into this one would hide which evidence carried which
change.

HOW THIS TEST CAN FAIL: a pressable control that assigns anything but a
constant into an expanded-state map.

COUNTER-CHECK (2026-09-25): red before - ToggleButton at cogs/control_ui.py
:797, ``self.cog.expanded_states[self.docker_name] = self.is_expanded``.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]

# What "a control" means here: a class whose base is a thing Discord renders
# for pressing. Asked of the BASE, not of the name - a sabotage that renames
# ToggleButton to Expander keeps its base and stays in the subject list.
PRESSABLE = ("Button", "Select")


def _controls(source: str):
    """(class name, class node) for every pressable control in one file."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            if ast.unparse(base).split(".")[-1] in PRESSABLE:
                yield node.name, node
                break


def _expand_state_writes(cls: ast.ClassDef):
    """Every assignment this control makes into an expanded-state map.

    Asked of the ASSIGNMENT TARGET, so a comment about the old toggle - or
    this docstring - cannot trip it, and a sabotage cannot dodge it by
    renaming the variable it assigns FROM.
    """
    for node in ast.walk(cls):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            if ast.unparse(target.value).endswith("expanded_states"):
                yield node.lineno, ast.unparse(target), node.value


def _findings():
    """Controls that write a COMPUTED value into an expanded-state map."""
    found, subjects = [], []
    for path in sorted((PROJECT / "cogs").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for name, cls in _controls(source):
            for line, target, value in _expand_state_writes(cls):
                subjects.append(f"{name}:{line}")
                if not isinstance(value, ast.Constant):
                    found.append(f"{path.name}:{line}: {name}: "
                                 f"{target} = {ast.unparse(value)}")
    return found, subjects


def test_no_pressable_control_flips_a_container_open_or_shut():
    """THE FINDING: the ➕/➖ toggle, which no caller could produce."""
    found, _subjects = _findings()

    assert found == [], (
        "an expand state is set by the panel that opens, not flipped by a "
        f"button - there is no expand/collapse control any more: {found}")


def test_the_scan_really_looks_at_the_controls_that_do_write_one():
    """The counter-check ten sabotages have walked past: a scan that matches
    nothing passes the case above while proving nothing.

    The mech DOES expand and collapse, with two buttons that each set their
    own constant. They have to be in the subject list, or this scan is
    reading an empty room.
    """
    _found, subjects = _findings()
    names = {entry.split(":")[0] for entry in subjects}

    assert {"MechExpandButton", "MechCollapseButton"} <= names, sorted(names)


def test_a_panel_may_still_say_what_it_shows():
    """The opposite mistake. Setting a constant is how a panel declares the
    state it is drawing, and a rule that forbade that too would empty the
    panel instead of fixing anything.

    IT USED TO NAME THE CONTAINER PANEL HERE - ``AdminContainerDropdown`` and
    ``ActionButton`` each wrote True before drawing. Both writes are gone
    (2026-09-25, tests/spec/test_a_panel_never_offers_to_expand.py): with no
    second rendering to choose between, the state they set had nothing left
    to decide. The mech's two writers are what is left to ask about.

    WHAT THIS CASE DOES NOT SAY. It does not say the mech's expand and
    collapse can be reached. They cannot: MechView, the view actually posted
    on the overview, carries neither, and the two buttons live only in the
    persistent views registered so old messages still answer after a restart
    (cogs/docker_control.py). That is a separate finding, recorded in
    test_a_panel_never_offers_to_expand.py. The rule here is narrower and
    still true wherever a control writes such a state: a constant is a panel
    naming what it draws, a computed value is a toggle.
    """
    _found, subjects = _findings()
    names = {entry.split(":")[0] for entry in subjects}

    assert "MechExpandButton" in names, sorted(names)

    _line, _target, value = next(
        write for name, cls in _controls((PROJECT / "cogs" / "control_ui.py")
                                         .read_text(encoding="utf-8"))
        if name == "MechExpandButton"
        for write in _expand_state_writes(cls))

    assert isinstance(value, ast.Constant), ast.unparse(value)


def test_a_flip_written_any_other_way_is_still_a_flip():
    """The scanner against a sabotage: the same write with a different name,
    a different base spelling and a different right-hand side."""
    sabotage = (
        "class Expander(discord.ui.Button):\n"
        "    async def callback(self, interaction):\n"
        "        self.cog.expanded_states[self.docker_name] = not self.shown\n")
    controls = dict(_controls(sabotage))

    assert "Expander" in controls, "the base was not recognised"

    writes = list(_expand_state_writes(controls["Expander"]))

    assert len(writes) == 1, writes
    assert not isinstance(writes[0][2], ast.Constant), ast.unparse(writes[0][2])


def test_a_correction_may_explain_what_used_to_be_there():
    """The mistake five of my own scans made today, from the other side: a
    comment describing the removed toggle must stay writable."""
    allowed = (
        "class Keeper(Button):\n"
        '    """This used to flip expanded_states[name] = not is_expanded."""\n'
        "    async def callback(self, interaction):\n"
        "        # expanded_states[x] = self.is_expanded - gone with the toggle\n"
        "        self.cog.expanded_states[self.docker_name] = True\n")
    controls = dict(_controls(allowed))
    writes = list(_expand_state_writes(controls["Keeper"]))

    assert len(writes) == 1, writes
    assert isinstance(writes[0][2], ast.Constant), ast.unparse(writes[0][2])

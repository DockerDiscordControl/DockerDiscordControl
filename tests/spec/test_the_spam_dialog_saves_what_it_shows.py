# -*- coding: utf-8 -*-
"""The spam dialog saves the fields it shows, and invents none.

THE FINDING (2026-09-26). The dialog READS its settings with a loop over
whatever the server sent::

    for (const [btn, cooldown] of Object.entries(data.button_cooldowns || {})) {
        const element = document.getElementById('button_' + btn);
        if (element) element.value = cooldown;
    }

and WROTE them back from twenty-four names typed into the file. Five of those
names have no field in the markup - ``admin_overview_admin``,
``_restart_all``, ``_stop_all``, ``_restart_stack``, ``_donate`` - so the save
reached for them with ``?.value || 5`` and wrote a number out of the source.
A cooldown the operator could not see, could not change, and that every press
of Save pinned into his configuration.

THE COMMENT ABOVE THOSE FIVE LINES HAD WARNED ABOUT THE SAME SHAPE, pointing
the other way: "a slider missing HERE is rendered and then dropped on save".
Somebody saw the two halves could disagree and added the ``?.`` rather than
removing the reason they could.

WHICH IS WHAT A LIST DOES: it goes stale exactly like the thing it guards -
the lesson this repository keeps relearning. The save now reads the same
fields the load fills, inside the dialog, so a field that exists is saved and
one that does not is not invented.

NOTHING IS LOST BY NOT SENDING ONE: spam_protection_service merges the saved
settings over its own defaults (services/infrastructure/spam_protection_service.py),
so a cooldown the dialog does not show keeps the default it always had.

HOW THIS TEST CAN FAIL: a save that writes a cooldown with no field, or skips
one that has a field.

COUNTER-CHECK (2026-09-26): red before - two of the six node cases.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests" / "js" / "spam_cooldowns.test.js"
SCRIPT = ROOT / "app" / "static" / "js" / "spam_protection_modal.js"
TEMPLATES = ROOT / "app" / "templates"


def _code_of(javascript):
    """The source with its line comments taken out.

    THE TENTH TIME IN THIS REPOSITORY that an explanation tripped the scan
    that the explanation was about: the note now standing in the save names
    the five ghosts in order to say they are gone, and the case below read
    that as them still being there. A scan about code has to read code.
    """
    return "\n".join(re.sub(r"//.*$", "", line) for line in javascript.splitlines())


def _fields_with(prefix):
    """Every id in the whole panel that starts with this prefix."""
    found = set()
    for path in sorted(TEMPLATES.rglob("*.html")):
        found |= set(re.findall(rf'id="({re.escape(prefix)}[\w-]*)"',
                                path.read_text(encoding="utf-8")))
    return found


def test_the_saving_cases_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/spam_cooldowns.test.js by hand")
    result = subprocess.run([node, str(CASES)], capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 6, result.stdout


def test_the_save_names_no_cooldown_of_its_own():
    """NODE CANNOT SEE A NAME THAT IS NOT REACHED. The point is that the
    source carries no list at all: one `admin_overview_donate:` left behind
    would be written on every save while every case in node stayed green."""
    source = SCRIPT.read_text(encoding="utf-8")
    body = _code_of(source[source.index("function saveSpamProtection("):])
    # A cooldown field fetched by a name written here, e.g.
    # `parseInt(document.getElementById('button_start').value)`. The two
    # global settings above the cooldowns are named here on purpose - they
    # are two fields, not a list that can drift - so the scan asks for the
    # two PREFIXES rather than for every literal key, which is what a first
    # version did and it called those two a finding.
    named = re.findall(r"getElementById\('((?:button_|cooldown_)[\w-]*)'\)", body)

    assert named == [], f"the save still names cooldowns of its own: {named}"
    assert "admin_overview" not in body, "the five ghosts are still in the save"


def test_it_reads_the_fields_instead():
    """And the replacement is the dialog, not a shorter list."""
    source = SCRIPT.read_text(encoding="utf-8")

    assert "readCooldowns('cooldown_')" in source
    assert "readCooldowns('button_')" in source
    assert "getElementById('spamProtectionModal')" in source[source.index("function readCooldowns"):], \
        "the save sweeps the whole page rather than the dialog"


def test_the_five_ghosts_really_have_no_field():
    """The premise, measured rather than remembered. If somebody adds the
    sliders one day this file should say so rather than quietly keep
    passing."""
    buttons = _fields_with("button_")

    assert len(buttons) >= 15, sorted(buttons)
    for ghost in ("button_admin_overview_admin", "button_admin_overview_donate",
                  "button_admin_overview_stop_all", "button_admin_overview_restart_all",
                  "button_admin_overview_restart_stack"):
        assert ghost not in buttons, (
            f"{ghost} now HAS a field - the save reads it by itself, and this "
            f"case is the one to update")


def test_no_field_elsewhere_would_be_swept_in():
    """The dialog is fenced, and this is why it had to be: the panel is one
    long document, and an id starting the same way anywhere on it would
    otherwise be saved as a cooldown."""
    outside = set()
    for path in sorted(TEMPLATES.rglob("*.html")):
        if path.name == "_spam_protection_modal.html":
            continue
        markup = path.read_text(encoding="utf-8")
        outside |= set(re.findall(r'id="((?:button_|cooldown_)[\w-]*)"', markup))

    # Nothing today, which is exactly when a fence is cheap. The fence itself
    # is asserted above; this records what it is protecting against.
    assert outside == set(), (
        f"these ids would be saved as cooldowns if the fence were removed: {sorted(outside)}")

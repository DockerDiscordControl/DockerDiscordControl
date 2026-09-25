# -*- coding: utf-8 -*-
"""The difficulty card promises an immediate save, so it has to make one.

THE OPERATOR, 2026-09-26, pointing at the Mech evolution difficulty card:
"you have to check this one too, whether it works at all."

IT DID NOT, in the one state where it can be used. The card says, in blue and
with a lightning bolt, ``web.advanced.difficulty_saved_immediately`` -
"changes are saved immediately" - and underneath it sit a slider and three
preset buttons. Both handlers ended at ``enableManualOverride()``, which
returns at once when the switch is ALREADY on - and the switch being on is
exactly what makes the slider and the buttons usable::

    function setDifficulty(value) { slider.value = value;
                                    updateDifficultyDisplay();
                                    enableManualOverride(); }

The only caller of ``saveMechDifficulty()`` was the modal's footer Save. So
the operator could drag to 2.00x, read "Current: 2.00x", close the dialog with
Cancel or the X, and keep the old value - while the panel had told him it was
already saved.

THE SENTENCE IS THE PART THAT IS RIGHT. It exists in forty catalogues and it
describes what a control with no Save button of its own ought to do, so the
controls were brought up to it rather than the sentence down to them. Writing
a new sentence would have meant authoring it in forty languages, which is not
something to invent.

THE RELEASE COMMITS, NOT THE DRAG: a range fires ``input`` for every step, so
the markup passes nothing from ``oninput`` and true from ``onchange``. One
decision, one request.

HOW THIS TEST CAN FAIL: a preset button or a released slider that writes
nothing, a drag that writes per step, or the markup no longer committing.

COUNTER-CHECK (2026-09-26): red before - the two writing cases in node.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests" / "js" / "mech_difficulty.test.js"
SCRIPT = ROOT / "app" / "static" / "js" / "advanced_settings_modal.js"
MARKUP = ROOT / "app" / "templates" / "_advanced_settings_modal.html"


def test_the_card_still_promises_an_immediate_save():
    """The premise. If the promise were dropped the cases below would be
    measuring a rule nobody made - and dropping it is not an option anyway,
    because the sentence exists in forty catalogues."""
    markup = MARKUP.read_text(encoding="utf-8")

    assert "web.advanced.difficulty_saved_immediately" in markup, (
        "the card no longer promises an immediate save")


def test_the_writing_cases_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here - run tests/js/mech_difficulty.test.js by hand")
    result = subprocess.run([node, str(CASES)], capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("ok   - ") == 6, result.stdout


def test_the_slider_commits_when_it_is_let_go():
    """NODE CANNOT SEE THE MARKUP. The handler now takes a flag, and if the
    tag never passed it the release would commit nothing while every case in
    node stayed green - a test that cannot fail the way the thing fails."""
    tag = next(t for t in re.findall(r"<input\b[^>]*>", MARKUP.read_text(encoding="utf-8"),
                                     re.S)
               if "mech_difficulty_multiplier" in t)

    assert "onchange=\"onSliderChange(true)\"" in tag, tag
    assert "oninput=\"onSliderChange()\"" in tag, (
        "the drag commits too - a range fires input for every step: " + tag)


def test_the_buttons_still_reach_the_same_handler():
    """The three presets are wired by an attribute, so a rename would leave
    them looking alive and doing nothing - the shape this whole card had."""
    markup = MARKUP.read_text(encoding="utf-8")
    pressed = re.findall(r'onclick="setDifficulty\(([0-9.]+)\)"', markup)

    assert sorted(float(v) for v in pressed) == [0.5, 1.0, 2.0], pressed
    assert "function setDifficulty(" in SCRIPT.read_text(encoding="utf-8")


def test_the_switch_reports_whether_it_saved():
    """The two callers ask it before saving themselves, or the first touch
    would post twice - once with manual_override false and once true."""
    source = SCRIPT.read_text(encoding="utf-8")
    body = source[source.index("function enableManualOverride("):]

    assert "return true;" in body and "return false;" in body, (
        "enableManualOverride says nothing about whether it saved")
    assert source.count("enableManualOverride()") >= 2, \
        "nobody asks it, so the answer is decoration"

# -*- coding: utf-8 -*-
"""A press waits for the container to answer, not for a fixed number of seconds.

THE OPERATOR'S SCREENSHOT (2026-09-24): after pressing a button the panel said

    ⏳ Processing...
    Updating container status...
    🔄 Please wait ~15 seconds

(he reads it in German) and then sat there for fifteen seconds. His question,
translated: does it have to be fifteen seconds - can we not simply wait for an
answer instead, capped, with an error message if the container does not come
up?

HE IS RIGHT, AND HALF OF IT WAS ALREADY THERE. The callback did this:

    1  show "in progress"
    2  run the docker action
    3  wait until the action shows, asking every few seconds, up to 26s
    4  show "Processing... please wait ~15 seconds"
    5  sleep(15)
    6  refresh and redraw

Step 3 already waits for the answer and returns the moment it has it. Steps 4
and 5 then announce a wait that had already happened and slept through it
blind. On a container that came up in three seconds the operator was told to
wait fifteen more, and did.

THE CAP WAS THERE TOO, AND NOBODY LOOKED AT IT. Step 3 gives up after 26
seconds and returned that fact to a caller that threw it away, so a container
that never came up was drawn exactly like one that did - stopped, no
explanation. That is the "error message if the container does not come up"
half of his question, and it is the half that was actually missing.

So: the blind sleep goes, the wait's verdict is read, and a press that could
not be confirmed says so.

HOW THIS TEST CAN FAIL: a fixed sleep back in the press path, or a wait whose
verdict is dropped again.

COUNTER-CHECK (2026-09-24): red before - control_ui.py held asyncio.sleep(15)
and the return value of the wait was assigned to nothing.
"""

import ast
import json
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
CONTROL_UI = PROJECT / "cogs" / "control_ui.py"

# Removed with the blind wait. A key left in the catalogues after its last
# reader is gone is a text nobody shows and nobody can find.
DROPPED = ("Please wait ~15 seconds", "Updating container status...", "Processing...")

# What a press that Docker accepted but nothing confirmed now says.
ADDED = ("⏱️ Not confirmed yet",
         "**{server_name}** was sent the {action_process_text} and Docker accepted it, "
         "but the status had not changed after {seconds} seconds. It may still be working.")


def _catalogues():
    return [p for p in sorted((PROJECT / "locales").glob("*.json")) if p.name != "meta.json"]


def test_no_press_sleeps_a_fixed_stretch():
    """THE FINDING: fifteen seconds of nothing, after the waiting was done."""
    tree = ast.parse(CONTROL_UI.read_text(encoding="utf-8"))
    fixed = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and "sleep" in ast.unparse(node.func)
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, (int, float))
                and node.args[0].value >= 5):
            fixed.append(f"line {node.lineno}: {ast.unparse(node)}")

    assert fixed == [], f"a press still waits on the clock: {fixed}"


def test_the_wait_says_whether_it_worked():
    """It always knew; the caller threw the answer away."""
    from cogs.action_effect import wait_until_the_action_took_effect

    source = ast.parse((PROJECT / "cogs" / "action_effect.py").read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(source)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "wait_until_the_action_took_effect")
    returns = [ast.unparse(node.value) for node in ast.walk(function)
               if isinstance(node, ast.Return) and node.value is not None]

    assert returns, "the wait returns nothing at all"
    assert wait_until_the_action_took_effect is not None


def test_the_button_reads_that_answer():
    """Assigned, not called and dropped - read from the syntax tree, because
    the call appears in a comment above it too."""
    tree = ast.parse(CONTROL_UI.read_text(encoding="utf-8"))
    assigned = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Await)
                and isinstance(node.value.value, ast.Call)
                and "wait_until_the_action_took_effect" in ast.unparse(node.value.value.func)):
            assigned.append(node.lineno)

    assert assigned, ("the wait's verdict is dropped again - a container that never "
                      "came up is drawn like one that did")


@pytest.mark.parametrize("text", ADDED)
def test_the_new_sentence_is_in_every_catalogue(text):
    missing = [p.name for p in _catalogues()
               if text not in json.loads(p.read_text(encoding="utf-8"))]

    assert missing == [], f"{text[:40]!r} missing from {len(missing)}: {missing[:5]}"


@pytest.mark.parametrize("text", ADDED)
def test_the_german_one_is_really_german(text):
    german = json.loads((PROJECT / "locales" / "de.json").read_text(encoding="utf-8"))

    assert german.get(text) != text, f"{text[:40]!r} is still the English text"


@pytest.mark.parametrize("text", DROPPED)
def test_the_dropped_sentences_are_gone_everywhere(text):
    """Removed from the code and left in the catalogues is a text nobody shows
    and nobody can find - and the sweep for dead keys only knows the dotted
    ones, so nothing else would notice."""
    left = [p.name for p in _catalogues()
            if text in json.loads(p.read_text(encoding="utf-8"))]

    assert left == [], f"{text!r} is still in {len(left)} catalogues: {left[:5]}"

    # Not a text search: the comment that explains the removal names the
    # sentence, and so does the docstring of the handler that used to be
    # stranded on it. What must be gone is the CALL - the literal handed to
    # the translator - which only the syntax tree can tell apart.
    tree = ast.parse(CONTROL_UI.read_text(encoding="utf-8"))
    translated = {node.args[0].value for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == "_" and node.args
                  and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, str)}

    assert text not in translated, f"{text!r} is still shown by control_ui.py"


def test_the_message_names_the_cap_it_waited_for():
    """The sentence says how long it waited, and the number comes from the
    ladder rather than being written out a second time - which is the defect
    the panel start values were about, one screen further on."""
    import ast

    from cogs.action_effect import RETRY_DELAYS

    source = (PROJECT / "cogs" / "action_effect.py").read_text(encoding="utf-8")
    builder = next(node for node in ast.walk(ast.parse(source))
                   if isinstance(node, ast.FunctionDef)
                   and node.name == "not_confirmed_embed")
    body = ast.unparse(builder)

    assert "RETRY_DELAYS" in body, "the seconds are written out instead of summed"
    assert sum(RETRY_DELAYS) == 26, sum(RETRY_DELAYS)

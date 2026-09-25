# -*- coding: utf-8 -*-
"""A private notice with nothing to click goes away by itself.

THE OPERATOR (2026-09-25): "one message builds up after another, and when the
process is finished I have to remove every one of them by hand with 'Dismiss
message'." He chose fifteen seconds.

WHAT THEY ARE. 173 calls across ten files send an ephemeral message with no
view, no embed and no file - pure text an operator reads once:

     17  Please wait {remaining:.1f} more seconds before using this button again.
     13  An error occurred. Please try again.
      7  Mech system is currently disabled.
      3  You don't have permission for this action.
      3  Another bulk operation is in progress. Please wait.
      2  This action is not allowed in this channel.

All 101 distinct texts are of that kind: a cooldown, a refusal, a failure. Not
one of them says "go and do something and come back", which is the only sort
that would need to stay. Read once, then clutter - and Discord leaves an
ephemeral message in place until its reader dismisses it one click at a time.

THE HOUSE STYLE ALREADY EXISTED, at three sites out of 176:
status_info_integration.py used delete_after=1 for "Refreshing..." and
"Updating...". The idea was right and had been applied exactly where somebody
happened to be standing - which is the shape of nearly every finding in this
repository.

THE LINE THIS DRAWS. A notice carries delete_after; a PANEL does not. A panel
is something to work with, and taking it away under the operator's hands would
be worse than leaving it - those are cleared up when their view expires
instead (test_a_finished_private_panel_takes_itself_away.py). The scan tells
them apart by whether the call carries view, embed or file, which is the same
question in code that "is there anything to click" is on screen.

HOW THIS TEST CAN FAIL: a new one-off ephemeral notice that stays until it is
dismissed by hand.

COUNTER-CHECK (2026-09-25): red before - 173 of 176 notices had no delete_after.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
COGS = PROJECT / "cogs"

# What a notice is DELIVERED by. Anything else - a channel send, a reply - is
# not an interaction answer and is not ephemeral.
A_NOTICE_CALL = ("response.send_message", "followup.send")
# What turns a notice into a panel: something on it to press or read at length.
MAKES_IT_A_PANEL = {"view", "embed", "file"}


def _ephemeral_calls():
    """(path, node, keywords) for every ephemeral=True interaction answer."""
    for path in sorted(COGS.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = ast.unparse(node.func)
            if not any(called.endswith(ending) for ending in A_NOTICE_CALL):
                continue
            keywords = {kw.arg: kw.value for kw in node.keywords}
            private = keywords.get("ephemeral")
            if not (isinstance(private, ast.Constant) and private.value is True):
                continue
            yield path.relative_to(PROJECT), node, keywords


def test_every_one_off_notice_clears_itself():
    """THE FINDING: 173 messages an operator had to dismiss one by one."""
    offenders = []
    for path, node, keywords in _ephemeral_calls():
        if keywords.keys() & MAKES_IT_A_PANEL:
            continue
        if "delete_after" not in keywords:
            offenders.append(f"{path}:{node.lineno}")

    assert offenders == [], (
        "these private notices stay until they are dismissed by hand, one click "
        f"each: {offenders}")


def test_the_scan_sees_the_notices_at_all():
    """Counter-check, the one nine sabotages have walked past. A scan that
    matches nothing passes the case above while proving nothing - and this one
    has an exclusion in it, so it could shrink to zero quietly."""
    notices = [1 for _p, _n, kw in _ephemeral_calls() if not (kw.keys() & MAKES_IT_A_PANEL)]

    assert len(notices) > 100, f"only {len(notices)} notices found - the scan has gone blind"


def test_a_panel_is_not_forced_to_vanish():
    """THE OTHER HALF, and the mistake this could easily have become. A panel
    is worked with; removing it under the operator's hands would be worse than
    leaving it. Panels go when their view expires, not on a timer."""
    panels = [f"{p}:{n.lineno}" for p, n, kw in _ephemeral_calls()
              if kw.keys() & MAKES_IT_A_PANEL and "delete_after" in kw]

    assert panels == [], f"a panel would disappear while it is being used: {panels}"


def test_the_panels_are_really_there():
    """Counter-check on the case above: if nothing counted as a panel it would
    pass while proving nothing."""
    panels = [1 for _p, _n, kw in _ephemeral_calls() if kw.keys() & MAKES_IT_A_PANEL]

    assert len(panels) > 20, f"only {len(panels)} panels found - the split has collapsed"


def test_the_notice_lasts_long_enough_to_read():
    """The operator picked fifteen seconds. A value near zero would technically
    satisfy the rule above and make every refusal unreadable, which is a worse
    failure than the clutter."""
    from cogs.ddc_ui import NOTICE_STAYS_FOR

    assert 5 <= NOTICE_STAYS_FOR <= 60, NOTICE_STAYS_FOR


def test_the_duration_is_named_once():
    """A number repeated 173 times cannot be changed; a name can. Every notice
    must use it rather than a literal of its own."""
    literals = []
    for path, node, keywords in _ephemeral_calls():
        if keywords.keys() & MAKES_IT_A_PANEL:
            continue
        stay = keywords.get("delete_after")
        if isinstance(stay, ast.Constant):
            literals.append(f"{path}:{node.lineno} delete_after={stay.value}")

    assert literals == [], (
        f"these hardcode the duration instead of using NOTICE_STAYS_FOR: {literals}")

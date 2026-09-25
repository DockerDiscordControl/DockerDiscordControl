# -*- coding: utf-8 -*-
"""The inactivity check says what it did, not what it was about to consider.

THE OPERATOR (2026-09-25): "I have the impression the messages in the status or
control channel are regularly recreated instead of updated - can you look in the
logs?" I looked, told him he was right, and was wrong. So was he, and we were
both wrong because of the same line:

    attempting regeneration:            36
    Starting inactivity regeneration:    0
    successfully regenerated:            0

NOTHING WAS BEING RECREATED. The loop already checks whether the last message in
the channel is its own overview and skips when it is - the messages were being
updated exactly as intended. But "Channel <id> has been inactive for 0:01:00,
attempting regeneration" is logged at INFO BEFORE that check, and the skip that
follows is logged at DEBUG. So the log announced, twice a minute, an action that
never happened: about 2,880 alarming lines a day for a loop doing its job.

A log that cries wolf costs more than silence. It cost the operator a wrong
diagnosis and me a wrong answer, and the next time something really does
regenerate, that line will be indistinguishable from the noise.

AND IT PAID DISCORD FOR THE ANSWER. Reaching "nothing to do" took fetch_channel
plus history(limit=3) - two API calls per channel per minute, some 5,760 a day -
for a question `channel.last_message_id` answers from the gateway cache with
none. The call is now made only when that cheap answer says something changed.

HOW THIS TEST CAN FAIL: an INFO line about a regeneration that does not happen,
or a channel asked over the network when the cached answer was enough.

COUNTER-CHECK (2026-09-25): red before - the INFO line stood above the check,
and the cheap comparison did not exist.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
LOOPS = PROJECT / "cogs" / "background_loops.py"


def _the_check():
    """The function that decides about regenerating on inactivity."""
    tree = ast.parse(LOOPS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = ast.unparse(node)
            if "has been inactive for" in body or "inactivity_threshold" in body:
                return node, body
    raise AssertionError("the inactivity check is gone")


def test_no_info_line_announces_a_regeneration_before_it_is_decided():
    """THE FINDING: 36 announcements, 0 regenerations."""
    _node, body = _the_check()
    announcements = [line.strip() for line in body.splitlines()
                     if "logger.info" in line and "attempting regeneration" in line]

    assert announcements == [], (
        "this is logged at INFO before anything is decided, so a loop that does "
        f"nothing still says it is about to: {announcements}")


def test_the_loop_still_says_when_it_really_regenerates():
    """Counter-check: silencing everything would pass the case above. A real
    regeneration is worth one line - it is rare and it changes what the
    operator sees in Discord."""
    _node, body = _the_check()

    assert "successfully regenerated" in body or "Starting inactivity regeneration" in body, (
        "a real regeneration now happens silently, which is the opposite mistake")


def test_the_cheap_answer_is_asked_first():
    """last_message_id comes from the gateway cache; fetch_channel and history
    are network calls. Two per channel per minute, to learn that nothing
    changed."""
    _node, body = _the_check()

    assert "last_message_id" in body, (
        "the loop pays Discord for an answer the cache already has")
    cheap = body.index("last_message_id")
    for costly in ("fetch_channel", "history("):
        assert costly not in body[:cheap], (
            f"{costly} is called before the cached comparison - the saving is lost")


def test_the_tracked_message_is_what_it_compares_against():
    """"Nothing changed" means OUR message is still the newest one.

    READ FROM THE SYNTAX TREE, and the second time of asking. The first
    version of this case searched the surrounding characters for
    "channel_server_message_ids" or "tracked", and a sabotage that replaced
    the whole set with `tracked_ids = {cached_last_id}` - a comparison that is
    true every single time, so the loop would never look again - kept the word
    "tracked" and sailed through green. The name proves nothing; where the set
    COMES FROM does.
    """
    node, _body = _the_check()

    # The membership test that decides the skip, and the name it asks.
    asked = [ast.unparse(test.comparators[0])
             for test in ast.walk(node)
             if isinstance(test, ast.Compare)
             and len(test.ops) == 1 and isinstance(test.ops[0], ast.In)
             and "last_message_id" in ast.unparse(test.left)]

    assert asked, "nothing compares the cached newest message against anything"

    # ...and that name must be built from the tracking map, not from itself.
    for name in asked:
        sources = [ast.unparse(assign.value) for assign in ast.walk(node)
                   if isinstance(assign, ast.Assign)
                   and name in [ast.unparse(t) for t in assign.targets]]

        assert sources, f"{name} is compared against but never assigned"
        assert any("channel_server_message_ids" in source for source in sources), (
            f"{name} does not come from the tracked overview ids, so the skip "
            f"is not about our own message: {sources}")


def test_the_skip_is_still_a_skip():
    """Counter-check on the whole change: the loop must still be ABLE to
    regenerate, or this would be a very quiet way of switching the feature
    off."""
    _node, body = _the_check()

    assert "_regenerate_channel" in body, "nothing regenerates any more"

# -*- coding: utf-8 -*-
"""Every place that reads the channel's control right also asks about the admin.

WHERE THIS RULE COMES FROM (review D3, pass 2, section 02 F3). A registered
admin may act where the channel alone permits nothing (SPEC.md Z5 with the B2
clarification), so each site decides the control right as

    channel permission for 'control'  OR  the user is a registered admin

One site did not: ``ToggleButton``'s own helper asked the channel alone, and a
registered admin pressing Expand in a status channel had the view rebuilt
without the ``or`` - the Stop and Restart buttons vanished until something
else redrew the message.

WHY THIS FILE REPLACES THE ONE THAT CAUGHT IT. That case drove the real
``ToggleButton``, and on 2026-09-25 that button was removed as unreachable
(tests/spec/test_a_panel_never_offers_to_expand.py). Deleting the case with
it would have taken the RULE down with the one site that broke it, while the
three sites that still decide the same thing went unwatched. So the rule is
asked of all of them at once, from the syntax tree, and it no longer depends
on any single class surviving.

WHY THE TREE AND NOT THE BEHAVIOUR: the mistake was never in what the rule
computes - it was a site that did not ask it. A behavioural case can only
press the buttons somebody remembered to list.

THE SECOND HALF the original report did not name, kept here because it is the
subtler error: being a registered admin is a property of the USER, while a
permission cache is keyed by CHANNEL. The ``or`` must therefore never be
computed inside something cached per channel, or the first presser's admin
status is handed to everybody else in the same channel.

HOW THIS TEST CAN FAIL: a site reading the 'control' permission without the
admin alternative beside it, or an admin check moved inside the per-channel
cache.

COUNTER-CHECK (2026-09-25): green here, and red when the ``or`` is taken off
any one of the three sites - see the sabotage case below.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
CONTROL_UI = PROJECT / "cogs" / "control_ui.py"

# The two spellings of "and the user is an admin" that live code uses. Asked
# as CALLED FUNCTIONS below, not as words in the line.
ADMIN_CHECKS = ("_is_registered_admin", "_admin_may_control")


def _control_permission_reads(source: str):
    """(line, enclosing expression) for every read of the 'control' right.

    Found by the CALL and its argument, so renaming the variable it lands in
    changes nothing, and a comment naming the helper is not a read.
    """
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree)
               for child in ast.iter_child_nodes(node)}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not ast.unparse(node.func).endswith("_get_cached_channel_permission"):
            continue
        if "'control'" not in [ast.unparse(a) for a in node.args]:
            continue

        enclosing = parents.get(node)
        while enclosing is not None and not isinstance(enclosing, (ast.BoolOp, ast.stmt)):
            enclosing = parents.get(enclosing)
        yield node.lineno, enclosing


def _sites_without_the_admin_alternative(source: str):
    found, seen = [], 0
    for line, enclosing in _control_permission_reads(source):
        seen += 1
        text = ast.unparse(enclosing) if enclosing is not None else ""
        if not (isinstance(enclosing, ast.BoolOp) and isinstance(enclosing.op, ast.Or)
                and any(check in text for check in ADMIN_CHECKS)):
            found.append(f"{line}: {text[:90]}")
    return found, seen


def test_no_site_decides_the_control_right_on_the_channel_alone():
    """THE RULE: a registered admin may act where the channel does not."""
    found, seen = _sites_without_the_admin_alternative(
        CONTROL_UI.read_text(encoding="utf-8"))

    assert seen >= 3, f"only {seen} sites found - the scan has lost its subject"
    assert found == [], (
        "a registered admin loses the control buttons at these places: "
        f"{found}")


def test_the_scan_would_see_the_site_that_broke_it():
    """The counter-check ten sabotages have walked past: a scan matching
    nothing passes the case above while proving nothing. This is the shape
    ToggleButton had - the channel asked on its own."""
    sabotage = (
        "def _control_allowed_for(self, channel_id, user_id, current_config):\n"
        "    return _get_cached_channel_permission(channel_id, 'control',"
        " current_config)\n")
    found, seen = _sites_without_the_admin_alternative(sabotage)

    assert seen == 1, seen
    assert len(found) == 1, found


def test_the_right_shape_is_accepted():
    """The opposite mistake: a scan that flags everything would force the
    ``or`` to be written some other way and prove nothing either."""
    allowed = (
        "def may(channel_id, user_id, config):\n"
        "    return (_get_cached_channel_permission(channel_id, 'control', config)\n"
        "            or _is_registered_admin(user_id))\n")
    found, seen = _sites_without_the_admin_alternative(allowed)

    assert seen == 1, seen
    assert found == [], found


def test_a_different_permission_is_not_this_rule():
    """'schedule' is its own right and carries no admin alternative. Pulling
    it into this rule would hand schedule rights to admins in a channel the
    operator did not give them."""
    other = (
        "def may(channel_id, config):\n"
        "    return _get_cached_channel_permission(channel_id, 'schedule', config)\n")
    _found, seen = _sites_without_the_admin_alternative(other)

    assert seen == 0, "the scan picked up a permission that is not 'control'"


def test_the_admin_answer_is_never_cached_per_channel():
    """The subtler half. A cache keyed by channel must hold the CHANNEL's
    answer only; an admin check inside it serves one user's rights to the
    next person in the same channel."""
    tree = ast.parse(CONTROL_UI.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = ast.unparse(node)
        caches_by_channel = "_channel_permissions_cache[" in body or (
            "_permission_cache[" in body and "channel_id" in body)
        if caches_by_channel and any(check in body for check in ADMIN_CHECKS):
            offenders.append(f"{node.name}:{node.lineno}")

    assert offenders == [], (
        "an admin check sits inside a cache keyed by channel - the first "
        f"presser's rights would be served to everyone else: {offenders}")

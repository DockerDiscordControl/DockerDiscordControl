# -*- coding: utf-8 -*-
"""A registered admin keeps the control buttons after pressing Expand.

THE FINDING (review D3, pass 2, section 02 F3): six places in control_ui.py
decide the control permission as

    channel permission for 'control'  OR  _is_registered_admin(user)

because a registered admin may act where the channel alone permits nothing
(SPEC.md Z5 with the B2 clarification). `ToggleButton`'s own helper,
`_get_cached_channel_permission_for_toggle`, was the one that did not. So an
admin in a status channel pressing Expand/Collapse had the view rebuilt
without the `or`, and the Stop/Restart buttons vanished until something else
redrew the message.

There is a second half the report did not name: the helper caches its answer
per CHANNEL, while being a registered admin is a property of the USER. The
`or` must therefore NOT go inside that cache, or the first presser's admin
status would be handed to everyone else in the same channel.
"""

from unittest.mock import MagicMock

import pytest

from cogs import control_ui

CHANNEL = 4242
ADMIN = 1001
ORDINARY = 1002


@pytest.fixture
def button(monkeypatch):
    """A ToggleButton without Discord, in a channel WITHOUT 'control'."""
    monkeypatch.setattr(control_ui, "_get_cached_channel_permission",
                        lambda channel_id, key, config: False)
    monkeypatch.setattr(control_ui, "_is_registered_admin", lambda user_id: user_id == ADMIN)

    instance = object.__new__(control_ui.ToggleButton)
    instance._channel_permissions_cache = {}
    return instance


def test_an_admin_may_control_in_a_status_channel(button):
    assert button._control_allowed_for(CHANNEL, ADMIN, {}) is True, (
        "a registered admin pressed Expand and lost the Stop/Restart buttons"
    )


def test_an_ordinary_user_still_may_not(button):
    """Counter-check: the channel rule still decides for everybody else."""
    assert button._control_allowed_for(CHANNEL, ORDINARY, {}) is False


def test_the_admin_answer_is_not_cached_for_the_channel(button):
    """The cache is keyed by channel; being an admin is a property of the user.
    An admin pressing first must not hand their rights to the next presser."""
    assert button._control_allowed_for(CHANNEL, ADMIN, {}) is True

    assert button._control_allowed_for(CHANNEL, ORDINARY, {}) is False, (
        "the admin's answer was cached under the channel and served to somebody else"
    )


def test_a_control_channel_needs_no_admin(button, monkeypatch):
    """Counter-check: where the channel permits it, everyone may."""
    monkeypatch.setattr(control_ui, "_get_cached_channel_permission",
                        lambda channel_id, key, config: True)

    assert button._control_allowed_for(CHANNEL, ORDINARY, {}) is True


def test_the_call_site_hands_over_the_real_user():
    """The tests above call the rule directly, so they cannot see whether the
    one place that uses it passes the pressing user at all. Without that, the
    rule is right and always asked about nobody (found by mutation M3 of
    review D3).
    """
    import ast
    import inspect

    # getsource of a top-level class is already at indent 0 and parses as is.
    # A first version de-indented it by hand and broke the class body.
    tree = ast.parse(inspect.getsource(control_ui.ToggleButton))

    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)
             and node.func.attr == "_generate_ultra_fast_toggle_embed_and_view"]

    assert calls, "the call this guards has gone - the guard has lost its subject"
    for call in calls:
        arguments = [ast.unparse(argument) for argument in call.args]
        assert "interaction.user.id" in arguments, (
            f"the view is rebuilt without the pressing user: {arguments}"
        )

# -*- coding: utf-8 -*-
"""The toggle button must have a cooldown like every other button.

NO ``@covers`` marker: that would be a new guarantee, and guarantees are the
operator's decision.

THE FINDING (SPEC.md B10, released for clarification by the operator).

Since a removal, ``ToggleButton.callback`` (``cogs/control_ui.py:662``) only
carries the note::

    # Note: Spam protection for toggle button was intentionally removed

No reason is given anywhere - neither in the comment nor in the commit
message. Every other button in the same file checks (``:265-282``,
``:981-990``, ``:1221-1228``). The toggle button is the only exception.

WHAT THE OPERATOR SEES OF IT: the button expands and collapses the container
display. Without a brake it can be pressed arbitrarily fast; every press
triggers a ``message.edit`` against the Discord API. It is the button with the
lowest inhibition threshold - it seemingly does nothing dangerous - and at the
same time the only one without protection.

THE REMOVAL WAS NOT A REFACTORING: the old code (``0195074^``) was
functional, used the key ``"refresh"`` and had proper error handling. It was
deleted without replacement.

RESTORING DOES NOT MEAN REVERTING. The old code deviated from today's house
pattern in two places, and both would have been a step back:

* Its message was an **untranslated** f-string; the house pattern at
  ``:274`` translates.
* It caught ``Exception``; the house pattern catches
  ``(RuntimeError, AttributeError, KeyError)`` with ``exc_info=True``.

THE EXISTING CATALOG ENTRY ``"... more seconds before using this button
again."`` (``locales/*.json:1453``) IS USED - the only one of the three
existing cooldown messages **without** an ``{action}`` placeholder. The
message at ``:274`` fills ``{action}`` from ``self.action``; ``ToggleButton``
has no such field, and inserting ``"refresh"`` there would mean showing the
user the word "refresh" on an expand button.

ABOUT THE KEY ``"refresh"`` - measured, not chosen: it occurs exactly once in
the entire application code, namely as an entry in the defaults dictionary
(``spam_protection_service.py:301``). NO other caller passes it, and the panel
offers no field for it (it knows ``live_refresh``, a different key). So nobody
shares a bucket with the toggle button.

THIS LEADS TO AN OPERATOR QUESTION that this test does NOT decide: because the
panel has no ``refresh`` field, the restored cooldown is fixed at 5 seconds
and cannot be changed there. That is exactly what was removed - but it
contradicts the principle "the panel decides". Whether a panel field should be
added is a value decision and belongs to the operator.

HOW IT IS CHECKED HERE: via the real ``ToggleButton`` and its real callback.
The spam service is replaced on the MODULE PATH
(``services.infrastructure.spam_protection_service.get_spam_protection_service``)
and NOT under ``cogs.control_ui`` - the import only happens *inside* the
method, a replacement on the calling module would miss. The same pattern is
used by ``tests/unit/audit_2026_09/test_pkg_b_control_ui.py:49-53``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import ToggleButton

SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"


def _interaction():
    """An interaction following the pattern of the existing UI tests."""
    interaction = MagicMock()
    interaction.user.id = 4711
    interaction.user.name = "tester"
    interaction.channel.id = 99
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.message = MagicMock()
    interaction.message.edit = AsyncMock()
    return interaction


def _button():
    """Builds the real button. ``expanded_states`` is a REAL dictionary.

    With a MagicMock, ``expanded_states.get(...)`` would be a MagicMock and
    thus truthy - the button would start "expanded", and the state check
    below would check nothing.
    """
    cog = MagicMock()
    cog.expanded_states = {}
    cog.pending_actions = {}
    server_config = {"docker_name": "probecontainer", "name": "Probe container"}
    return cog, ToggleButton(cog, server_config, is_running=True, row=0)


def _service(on_cooldown, *, enabled=True, remaining=4.2):
    service = MagicMock()
    service.is_enabled.return_value = enabled
    service.is_on_cooldown.return_value = on_cooldown
    service.get_remaining_cooldown.return_value = remaining
    return service


def test_the_button_can_be_built_at_all():
    """Safeguard against a blunt tool.

    Must be green BEFORE and AFTER the fix. If building already failed, the
    tests below would be red without saying anything about the cooldown.
    """
    cog, button = _button()

    assert button.custom_id == "toggle_probecontainer"
    assert button.is_expanded is False
    assert cog.expanded_states == {}


@pytest.mark.asyncio
async def test_on_cooldown_the_press_is_rejected():
    """THE FINDING: the toggle button does not brake.

    Three assertions, each checkable on its own: nothing is acknowledged
    (``defer``), the state does not flip, and the user gets a reply visible
    only to them.
    """
    cog, button = _button()
    interaction = _interaction()

    with patch(SPAM_PATH, return_value=_service(on_cooldown=True)):
        await button.callback(interaction)

    interaction.response.defer.assert_not_awaited()
    assert cog.expanded_states == {}, (
        "The state flipped despite the cooldown. Then the button does not "
        "brake the display, only the reply - on the next build the container "
        "would be shown the wrong way round."
    )
    interaction.response.send_message.assert_awaited_once()
    kwargs = interaction.response.send_message.await_args.kwargs
    assert kwargs.get("ephemeral") is True, (
        "The rejection must be visible only to the presser - otherwise the "
        "brake itself creates channel noise."
    )
    text = interaction.response.send_message.await_args.args[0]
    assert "4.2" in text, (
        f"The remaining time is not in the message: {text!r}. Without it the "
        "user does not know how long to wait."
    )


@pytest.mark.asyncio
async def test_without_cooldown_the_lock_is_set():
    """THE FINDING, second half: a press must set the lock.

    Without this part a fix could only query and never record - the brake
    would then never apply.
    """
    cog, button = _button()
    interaction = _interaction()
    service = _service(on_cooldown=False)

    with patch(SPAM_PATH, return_value=service), \
            patch("cogs.control_ui.load_config", return_value={}):
        await button.callback(interaction)

    service.add_user_cooldown.assert_called_once_with(4711, "refresh")
    service.is_on_cooldown.assert_called_once_with(4711, "refresh")
    interaction.response.defer.assert_awaited_once()


@pytest.mark.asyncio
async def test_with_spam_protection_disabled_nothing_brakes():
    """Boundary: the operator can switch the protection off.

    If the check applied even then, the fix would be green for the wrong
    reason - it would override a setting.
    """
    cog, button = _button()
    interaction = _interaction()
    service = _service(on_cooldown=True, enabled=False)

    with patch(SPAM_PATH, return_value=service), \
            patch("cogs.control_ui.load_config", return_value={}):
        await button.callback(interaction)

    interaction.response.defer.assert_awaited_once()
    service.is_on_cooldown.assert_not_called()


@pytest.mark.asyncio
async def test_an_error_in_the_spam_service_does_not_block_the_button():
    """Boundary: the brake must never make the button unusable.

    The house pattern catches (RuntimeError, AttributeError, KeyError) and
    carries on. Without this boundary a fix could kill the button completely
    when the service malfunctions.
    """
    cog, button = _button()
    interaction = _interaction()
    service = _service(on_cooldown=False)
    service.is_on_cooldown.side_effect = RuntimeError("service disrupted")

    with patch(SPAM_PATH, return_value=service), \
            patch("cogs.control_ui.load_config", return_value={}):
        await button.callback(interaction)

    interaction.response.defer.assert_awaited_once()

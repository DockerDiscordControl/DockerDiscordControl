# -*- coding: utf-8 -*-
"""The refresh button of the live log view must brake through the spam service.

NO ``@covers`` marker: that would be a new guarantee, and guarantees are the
operator's decision.

THE FINDING. ``LiveLogView.manual_refresh`` (``status_info_integration.py:494``)
only fetches the DURATION from the service and does the bookkeeping itself:
timestamps under ``button_refresh_<user>`` in ``self._button_cooldowns``, a
dictionary the view creates for itself via ``hasattr``.
``is_on_cooldown`` and ``add_user_cooldown`` are never called.

TWO CONSEQUENCES:

1. The PER-MINUTE LIMIT from the panel has no effect here - it counts in
   ``add_user_cooldown``, and this path never gets there.
2. The lock hangs on the VIEW and dies with it. That weighs particularly
   heavily here: the live log view **renews itself** (see
   ``_start_auto_recreation``: 30 seconds before the timeout it is rebuilt).
   So whoever waits until the view has renewed itself is rid of any
   cooldown - without any of this being visible.

TAKEN ALONG: the rejection is today an UNTRANSLATED f-string
(``f"⏰ Please wait ... before refreshing again."``). The switch to the house
pattern uses the existing catalog entry.

NO NEW KEY: ``live_refresh`` exists in the defaults (5).

WHY THE ARGUMENT IS CHECKED HERE AND NOT THE VALUE:
``live_refresh`` is set to 5 - and 5 is also the fallback rule for UNKNOWN
names (``get_button_cooldown:186``). So a wrong key would return the same
number. A value check would be blunt here; adding it later would seemingly
sharpen the test and would not.

FOUR TRAPS OF THE FIXTURE, all sealed before the first run - in this session
two of them each cost me half a detour, because I only read them in the error
text:

1. ``__init__`` starts an asyncio task via ``_start_auto_recreation``.
   Without a running loop that would give a RuntimeError or a hanging task -
   so the method is replaced BEFORE the view is built.
2. ``response.send_message`` is used by the rejection (:507) AND the success
   path (:518, with ``delete_after=1``). An ``assert_awaited_once`` would
   therefore be satisfied even without a brake. Hence the WORDING.
3. The deep path expects ``container_logs_text`` - without a replacement the
   accepted press would run into a dummy dead end.
4. ``manual_refresh`` is NOT a button class of its own, but a method that is
   assigned to a button in ``_create_all_buttons``
   (``refresh_button.callback = self.manual_refresh``). So the view and its
   method are checked, not a button class.
5. NOISE FROM THE FIXTURE, so that nobody mistakes it for a defect:
   ``container_logs_text`` is replaced by an AsyncMock that returns an EMPTY
   string. The success path treats that as a failure and logs "Manual
   refresh failed - no logs retrieved" - in every run, several times. That
   has no consequence for the assertions, because they all lie BEFORE that
   point. Whoever reads the run output later should know that this warning
   comes from this test and not from the code.

``ephemeral`` and the EXACT ID are asserted from the start: the mutation
probe showed twice in this session that exactly these two assertions are
missing if you do not write them down explicitly.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.status_info_integration import LiveLogView
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"
USER = 7788
CONTAINER = "probecontainer"


class _Recorder:
    """Passes through to the REAL service and records what was asked."""

    def __init__(self, real):
        self._real = real
        self.asked = []
        self.recorded = []

    def is_on_cooldown(self, user_id, action_type):
        self.asked.append((user_id, action_type))
        return self._real.is_on_cooldown(user_id, action_type)

    def add_user_cooldown(self, user_id, action_type):
        self.recorded.append((user_id, action_type))
        return self._real.add_user_cooldown(user_id, action_type)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _service(tmp_path):
    return _Recorder(SpamProtectionService(config_dir=str(tmp_path)))


def _view():
    """Builds the REAL view - without starting the self-renewal task."""
    with patch.object(LiveLogView, "_start_auto_recreation", lambda self: None):
        return LiveLogView(CONTAINER, auto_refresh=False)


def _interaction():
    interaction = MagicMock()
    interaction.user.id = USER
    interaction.user.name = "tester"
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


async def _press(view, service):
    interaction = _interaction()
    with patch(SPAM_PATH, return_value=service), \
            patch("cogs.status_info_integration.container_logs_text",
                  new=AsyncMock(return_value="")):
        await view.manual_refresh(interaction)
    return interaction


@pytest.mark.asyncio
async def test_the_view_carries_the_refresh_button():
    """Safeguard against a blunt tool - EXACT ID, not mere existence.

    MUST be async: ``discord.ui.View.__init__`` calls
    ``asyncio.get_running_loop()`` (py-cord view.py:186). Built synchronously
    the view raises ``RuntimeError: no running event loop`` - replacing
    ``_start_auto_recreation`` is not enough, because the loop requirement
    comes from the base class, not from DDC code.
    """
    view = _view()

    ids = [k.custom_id for k in view.children]
    assert "manual_refresh" in ids, (
        f"The view carries no button with the ID 'manual_refresh': {ids}"
    )
    assert view.container_name == CONTAINER


def test_live_refresh_is_set_to_the_fallback_value(tmp_path):
    """Second safeguard - it records what can NOT be checked here.

    ``live_refresh`` is set to 5, and 5 is also the fallback rule for unknown
    names. So the VALUE cannot tell whether the right key is queried - the
    tests below check the ARGUMENT. If this changes, the tests may be
    sharpened.
    """
    service = SpamProtectionService(config_dir=str(tmp_path))

    assert service.get_button_cooldown("live_refresh") == 5
    assert service.get_button_cooldown("does_not_exist") == 5, "Fallback rule changed"


@pytest.mark.asyncio
async def test_the_service_is_asked_and_records(tmp_path):
    """THE FINDING: the stateful methods are never called."""
    service = _service(tmp_path)
    view = _view()

    await _press(view, service)

    assert service.asked == [(USER, "live_refresh")], (
        f"is_on_cooldown was not called with 'live_refresh', but "
        f"{service.asked!r}. The button brakes past the service and does not "
        "count towards the per-minute limit."
    )
    assert service.recorded == [(USER, "live_refresh")], (
        f"The accepted press was not recorded ({service.recorded!r})."
    )


@pytest.mark.asyncio
async def test_the_second_press_is_rejected(tmp_path):
    """THE FINDING, effect - and the message must be translated."""
    service = _service(tmp_path)
    view = _view()
    service.add_user_cooldown(USER, "live_refresh")
    service.recorded.clear()

    interaction = await _press(view, service)

    interaction.response.send_message.assert_awaited_once()
    args = interaction.response.send_message.await_args.args
    kwargs = interaction.response.send_message.await_args.kwargs
    assert args, "The rejection carries no text."
    assert "Refreshing logs" not in args[0], (
        f"The success message was sent ({args[0]!r}) - the button did not "
        "brake but refreshed."
    )
    assert "before using this button again" in args[0], (
        f"What was sent is not the catalog text but {args[0]!r}. The "
        "untranslated f-string reaches every user in English."
    )
    assert kwargs.get("ephemeral") is True, (
        "The rejection is not restricted to the presser and therefore "
        "appears for EVERYONE in the channel."
    )


@pytest.mark.asyncio
async def test_the_storage_on_the_view_is_gone(tmp_path):
    """THE FINDING, third part: no lock that dies with the view.

    Particularly consequential here, because the view renews itself - a lock
    on it is gone after the next renewal.
    """
    service = _service(tmp_path)
    view = _view()

    await _press(view, service)

    assert not getattr(view, "_button_cooldowns", None), (
        f"The view still keeps {getattr(view, '_button_cooldowns', None)!r} "
        "- this lock does not survive the next self-renewal."
    )

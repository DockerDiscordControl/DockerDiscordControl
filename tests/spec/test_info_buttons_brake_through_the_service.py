# -*- coding: utf-8 -*-
"""The three info buttons must brake through the spam service - with their OWN bucket.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. Three buttons in ``status_info_integration.py`` only fetch the
DURATION from the service and keep the bookkeeping themselves, in the cog's
dictionary::

    ProtectedInfoEditButton  :167  button_protected_edit_<user>  duration from "info"
    EditInfoButton           :237  button_info_<user>            duration from "info"
    ProtectedInfoButton      :1022 button_protected_<user>       duration from "info"

``is_on_cooldown`` and ``add_user_cooldown`` are never called. So the
PER-MINUTE LIMIT from the panel does not apply to these three - it counts in
``add_user_cooldown``, and they never get there.

WHAT MUST NOT CHANGE FOR THE USER, and this is the tricky part: the three
currently have THREE SEPARATE buckets, but fetch their duration jointly under
``"info"``. Simply switching them to ``is_on_cooldown(uid, "info")`` would
merge three locks into one - whoever opens the info could then not edit the
info for several seconds. That would be a noticeable tightening that nobody
decided on.

So each button gets its OWN action name, and the three names need an entry in
the defaults with the value **3** - exactly what ``"info"`` returns today.
Without an entry they would fall back to the 5-second fallback rule
(``get_button_cooldown:186``) and be SLOWER than today::

    protected_info_edit  3
    edit_info            3
    protected_info       3

FOUR TRAPS OF THE FIXTURE, named in advance:

1. The cog must NOT be a bare ``MagicMock`` - the current code asks
   ``hasattr(self.cog, '_button_cooldowns')``, and a MagicMock always says yes.
   The button would never refuse, and the test would check the dummy.
2. ``response.send_message`` is used by the refusal (:174/:244/:1029) AND by
   the error path (:206/:276/:1062). A mere ``assert_awaited_once`` would
   therefore also be satisfied by an error deep down. Hence additionally the
   WORDING and the check that ``send_modal`` was NOT called - that is the
   success path (:200/:270/:1056).
3. All three callbacks end in ``except Exception``; errors from deep down are
   swallowed. A test that only checks for the absence of errors would be
   hollow green. Here only POSITIVE assertions are made.
4. The service is a REAL ``SpamProtectionService`` on ``tmp_path``, only passed
   through for recording - a pure dummy would return any number.

SCOPE: patching happens on the MODULE PATH, because the import only happens
INSIDE the method. And this test says nothing about the nine other places that
also keep their own bookkeeping - separate findings.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.status_info_integration import (
    EditInfoButton,
    ProtectedInfoButton,
    ProtectedInfoEditButton,
)
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"
USER = 9317
CONTAINER = {"docker_name": "probe", "name": "Probe container"}

# Class -> expected action name. Deliberately one name each: the three keep
# separate buckets today, and that must stay so.
BUTTONS = [
    (ProtectedInfoEditButton, "protected_info_edit"),
    (EditInfoButton, "edit_info"),
    (ProtectedInfoButton, "protected_info"),
]


class _Recorder:
    """Passes through to the REAL service and records what was asked."""

    def __init__(self, real):
        self._real = real
        self.asked = []
        self.noted = []

    def is_on_cooldown(self, user_id, action_type):
        self.asked.append((user_id, action_type))
        return self._real.is_on_cooldown(user_id, action_type)

    def add_user_cooldown(self, user_id, action_type):
        self.noted.append((user_id, action_type))
        return self._real.add_user_cooldown(user_id, action_type)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _service(tmp_path):
    return _Recorder(SpamProtectionService(config_dir=str(tmp_path)))


def _cog():
    """Cog with a REAL dictionary - see trap 1 in the header."""
    cog = MagicMock()
    cog._button_cooldowns = {}
    return cog


def _interaction():
    interaction = MagicMock()
    interaction.user.id = USER
    interaction.channel.id = 3
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _build(button_class, cog):
    return button_class(cog, CONTAINER, {})


async def _press(button, service):
    interaction = _interaction()
    with patch(SPAM_PATH, return_value=service):
        await button.callback(interaction)
    return interaction


def test_the_three_buttons_can_be_built():
    """Safeguard against a blunt tool - green before and after the fix."""
    for button_class, _name in BUTTONS:
        button = _build(button_class, _cog())
        assert button.container_name == "probe", f"{button_class.__name__} does not build"


def test_the_three_names_have_the_current_value(tmp_path):
    """Second safeguard, and the more important one: NO silent slowdown.

    The three new names must return 3 - the current value of "info".
    If an entry is missing, the fallback rule with 5 applies, and the buttons
    would be slower than before without anybody having decided so.
    """
    service = SpamProtectionService(config_dir=str(tmp_path))

    assert service.get_button_cooldown("info") == 3, "Reference value has changed"
    assert service.get_button_cooldown("does_not_exist") == 5, "Fallback rule has changed"
    for _button_class, name in BUTTONS:
        assert service.get_button_cooldown(name) == 3, (
            f"{name!r} returns {service.get_button_cooldown(name)} instead of 3 - the "
            "button would be slower than today after the switch."
        )


@pytest.mark.parametrize("button_class,name", BUTTONS, ids=lambda x: getattr(x, "__name__", x))
@pytest.mark.asyncio
async def test_the_service_is_asked_and_noted(tmp_path, button_class, name):
    """THE FINDING: the stateful methods are never called."""
    service = _service(tmp_path)
    button = _build(button_class, _cog())

    await _press(button, service)

    assert service.asked == [(USER, name)], (
        f"{button_class.__name__}: is_on_cooldown was not called with {name!r}, "
        f"but {service.asked!r}. The button brakes past the service and does "
        "not count toward the per-minute limit."
    )
    assert service.noted == [(USER, name)], (
        f"{button_class.__name__}: the accepted press was not noted "
        f"({service.noted!r})."
    )


@pytest.mark.parametrize("button_class,name", BUTTONS, ids=lambda x: getattr(x, "__name__", x))
@pytest.mark.asyncio
async def test_the_second_press_is_refused(tmp_path, button_class, name):
    """THE FINDING, effect: what is in the service must brake the button."""
    service = _service(tmp_path)
    button = _build(button_class, _cog())
    service.add_user_cooldown(USER, name)
    service.noted.clear()

    interaction = await _press(button, service)

    interaction.response.send_modal.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()
    args = interaction.response.send_message.await_args.args
    assert args, "The refusal carries no text - that is how the error path calls, not the brake."
    assert "before using this button again" in args[0], (
        f"What was sent is not the cooldown refusal: {args[0]!r}"
    )
    assert interaction.response.send_message.await_args.kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_the_three_do_not_lock_each_other(tmp_path):
    """THE TRICKY PART: separate buckets, as today.

    Without this test a fix would be green that puts all three on the same
    key - and thereby merges three locks into one.
    """
    service = _service(tmp_path)
    service.add_user_cooldown(USER, "protected_info_edit")

    button = _build(EditInfoButton, _cog())
    interaction = await _press(button, service)

    interaction.response.send_modal.assert_awaited_once()
    interaction.response.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_own_bookkeeping_on_the_cog_is_dropped(tmp_path):
    """One store instead of two - otherwise the next fix is made in only one
    of the two places."""
    service = _service(tmp_path)
    cog = _cog()
    button = _build(ProtectedInfoEditButton, cog)

    await _press(button, service)

    assert cog._button_cooldowns == {}, (
        f"The button still writes into cog._button_cooldowns "
        f"({cog._button_cooldowns!r}) - the same information in two places."
    )

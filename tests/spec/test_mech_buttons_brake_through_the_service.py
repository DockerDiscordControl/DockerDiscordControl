# -*- coding: utf-8 -*-
"""The three braking mech buttons must brake through the spam service.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. Three mech buttons only fetch the DURATION from the service and
store their timestamp as an attribute on themselves (``_last_click_<user>``)::

    MechExpandButton    control_ui.py:2327   self.custom_id -> mech_expand
    MechCollapseButton  control_ui.py:2428   self.custom_id -> mech_collapse
    MechHistoryButton   control_ui.py:2563   self.custom_id -> mech_history

``is_on_cooldown`` and ``add_user_cooldown`` are never called. The
PER-MINUTE LIMIT from the panel therefore does not apply to them - it counts in
``add_user_cooldown``, and they never get there. The lock also dies with the
button object: on every rebuild of the view it is gone.

THE KEY STAYS ``self.custom_id``, and that is important: these three
query via the prefix logic (``get_button_cooldown:178-184``), which derives the
slider ``mech_expand`` from ``mech_expand_<channel>``. The service must be
fed with THE SAME value - a literal ``"mech_expand"`` would give a different
bucket than today, and ``interaction.user.id`` with a channel-specific name
one bucket per channel instead of per button kind. The test therefore nails
down the EXACT argument value.

HERE THE VALUE IS CHECKABLE TOO, unlike admin/help/tasks: the defaults
are 3 (expand), 2 (collapse) and 5 (history) - three different numbers,
none of them equal to the 5-second fallback rule for collapse and expand. A
wrong key thus stands out twice.

TWO REFUSAL ROUTES, MEASURED - no uniform pattern::

    MechExpandButton    brakes BEFORE the defer (:2338), refuses via
                        response.send_message
    MechCollapseButton  likewise (defer :2439)
    MechHistoryButton   acknowledges INSIDE the brake block (:2571) and
                        refuses via followup.send

A test that assumes the same route for all three would be red for one of them
for the wrong reason.

THE DONATION CHECK COMES BEFORE THE BRAKE FOR EXPAND AND COLLAPSE (:2311/:2418).
Without a replacement the callback returns before any key is queried -
and the test would be green without proving anything. For history it only
comes after the brake (:2588).

TWO ASSERTIONS ARE HERE FROM THE START, because the mutation probe revealed
them as a gap in the previous round: ``ephemeral`` is checked explicitly
(a refusal without it appears for EVERYONE in the channel - the brake would
then create the noise it is meant to prevent), and the id is checked for
its EXACT value, not for mere existence.

DELIMITATION: the TEN mech classes that do not brake at all are not the
subject of this test - that is a separate finding with a separate behaviour
change already approved by the operator.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import MechCollapseButton, MechExpandButton, MechHistoryButton
from services.infrastructure.spam_protection_service import SpamProtectionService
from tests.spec import is_not_awaitable_error

SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"
USER = 6644
CHANNEL = 77

# class -> (id prefix, slider name, default value, refusal route)
BUTTONS = [
    (MechExpandButton, "mech_expand", 3, "send_message"),
    (MechCollapseButton, "mech_collapse", 2, "send_message"),
    (MechHistoryButton, "mech_history", 5, "followup"),
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


def _interaction():
    interaction = MagicMock()
    interaction.user.id = USER
    interaction.user.name = "tester"
    interaction.channel.id = CHANNEL
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.message = MagicMock()
    interaction.message.edit = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    return interaction


async def _press(button, service):
    """Keep donations ACTIVE - otherwise the callback returns before the brake.

    ``_start_interaction`` must be an ``AsyncMock``: expand and collapse
    call it with ``await`` after the ``defer``, and a bare ``MagicMock``
    is not awaitable ("'MagicMock' object can't be awaited"). This danger
    was noted before the first run - afterwards I wrongly declared it as
    not having occurred, because pytest reports an unhandled exception in an
    asynchronous test as FAILED and not as ERROR. The label does not carry
    this distinction.
    """
    interaction = _interaction()
    button.cog._start_interaction = AsyncMock(return_value=True)
    with patch(SPAM_PATH, return_value=service), \
            patch("cogs.control_ui.is_donations_disabled", return_value=False):
        try:
            await button.callback(interaction)
        except TypeError as e:
            # ONLY TypeError, and only from the depths: after the brake the
            # callback calls a chain of cog methods with await
            # (_create_overview_embed_expanded, _end_interaction in the
            # cleanup path, ...). Each is not awaitable on a MagicMock,
            # and every repair of the fixture exposes the next one - an
            # arms race that says nothing about the brake.
            #
            # The swallowing is narrowly limited: the tests afterwards assert
            # POSITIVELY (asked/noted are filled, the refusal
            # was sent). A TypeError from the BRAKE would thus not be
            # hidden but visible as an empty recording.
            if not is_not_awaitable_error(e):
                raise
    return interaction


def _sender(interaction, route):
    return interaction.followup.send if route == "followup" else interaction.response.send_message


def test_the_three_buttons_carry_the_expected_id():
    """Safeguard against a blunt tool - EXACT value, not mere existence.

    The previous round showed that an ``assert button.custom_id`` cannot
    fire at all; a falsified id satisfies it effortlessly.
    """
    for button_class, prefix, _value, _route in BUTTONS:
        button = button_class(MagicMock(), CHANNEL)
        assert button.custom_id == f"{prefix}_{CHANNEL}", (
            f"{button_class.__name__} carries {button.custom_id!r} instead of "
            f"{prefix}_{CHANNEL!r}."
        )


def test_the_three_sliders_have_different_values(tmp_path):
    """Second safeguard: the value checks below are only worth something if the
    sliders differ - and if they deviate from the fallback rule.
    """
    service = SpamProtectionService(config_dir=str(tmp_path))

    assert service.get_button_cooldown("does_not_exist") == 5, "Fallback rule changed"
    measured_values = {}
    for _button_class, prefix, value, _route in BUTTONS:
        measured = service.get_button_cooldown(f"{prefix}_{CHANNEL}")
        assert measured == value, (
            f"{prefix} returns {measured} instead of {value} - the prefix logic "
            "no longer works as assumed."
        )
        measured_values[prefix] = measured
    assert len(set(measured_values.values())) == 3, f"Sliders no longer different: {measured_values}"


@pytest.mark.parametrize("button_class,prefix,value,route", BUTTONS, ids=lambda x: str(x))
@pytest.mark.asyncio
async def test_the_service_is_asked_and_noted(tmp_path, button_class, prefix, value, route):
    """THE FINDING: the stateful methods are never called."""
    service = _service(tmp_path)
    button = button_class(MagicMock(), CHANNEL)

    await _press(button, service)

    button_id = f"{prefix}_{CHANNEL}"
    assert service.asked == [(USER, button_id)], (
        f"{button_class.__name__}: is_on_cooldown was not called with {button_id!r}, "
        f"but {service.asked!r}. The button brakes past the service and "
        "does not count towards the per-minute limit."
    )
    assert service.noted == [(USER, button_id)], (
        f"{button_class.__name__}: The accepted press was not noted "
        f"({service.noted!r})."
    )


@pytest.mark.parametrize("button_class,prefix,value,route", BUTTONS, ids=lambda x: str(x))
@pytest.mark.asyncio
async def test_the_second_press_is_refused(tmp_path, button_class, prefix, value, route):
    """THE FINDING, effect - on the refusal route THIS button uses."""
    service = _service(tmp_path)
    button = button_class(MagicMock(), CHANNEL)
    button_id = f"{prefix}_{CHANNEL}"
    service.add_user_cooldown(USER, button_id)
    service.noted.clear()

    interaction = await _press(button, service)
    sender = _sender(interaction, route)

    sender.assert_awaited_once()
    args = sender.await_args.args
    assert args, (
        f"{button_class.__name__}: The refusal carries no text - that is how the "
        "deep path calls, not the brake."
    )
    assert "before using this button again" in args[0], (
        f"{button_class.__name__}: What was sent was not the catalog text, but "
        f"{args[0]!r}."
    )
    assert sender.await_args.kwargs.get("ephemeral") is True, (
        f"{button_class.__name__}: The refusal is not restricted to the presser "
        "and therefore appears for EVERYONE in the channel."
    )


@pytest.mark.parametrize("button_class,prefix,value,route", BUTTONS, ids=lambda x: str(x))
@pytest.mark.asyncio
async def test_the_volatile_storage_on_the_object_is_gone(tmp_path, button_class, prefix, value, route):
    """THE FINDING, third part: no lock that dies with the object."""
    service = _service(tmp_path)
    button = button_class(MagicMock(), CHANNEL)

    await _press(button, service)

    leftovers = [a for a in dir(button) if a.startswith("_last_click_")]
    assert not leftovers, (
        f"{button_class.__name__} still stores {leftovers} on the object. This lock "
        "is gone on the next rebuild of the view."
    )

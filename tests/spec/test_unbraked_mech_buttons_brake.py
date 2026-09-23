# -*- coding: utf-8 -*-
"""Mech buttons whose panel sliders move nothing today must brake.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision. The BEHAVIOUR CHANGE itself has been decided:
"Yes, let the ten brake too".

THE FINDING. The panel shows sliders for ``mech_donate`` (10), ``mech_display``
(3), ``mech_story`` (5) and ``mech_music`` (8). The corresponding buttons do
not ask the spam service at all::

    MechDonateButton    mech_donate_<channel>   -> mech_donate
    MechDisplayButton   mech_display_<level>    -> mech_display
    ReadStoryButton     read_story_<level>      -> (reaches no slider)
    PlaySongButton      play_song_<level>       -> (reaches no slider)
    EpilogueButton      epilogue_button         -> (reaches no slider)

The operator sets four sliders, and none of them brakes anything; the buttons
also bypass the per-minute limit.

"TEN" TURNED INTO FIVE WHEN MEASURED. The question to the operator counted
thirteen mech classes minus three braking ones. But among them are four views
(they do not brake themselves, their buttons do), a label field with
``disabled=True`` and two private buttons that FORWARD to MechDonateButton and
MechHistoryButton respectively. So the private history button already brakes
today, and the private donate button brakes with the public one. On the other
hand ReadStory, PlaySong and Epilogue were missing from the count - they are
not called "Mech...". My earlier statement "there is no class for mech_music"
was wrong: PlaySongButton is that class. MechDetailsButton does not brake
either, but has no slider at all - a separate finding.

THE NAMES, and why not ``self.custom_id`` everywhere: the prefix logic in
``get_button_cooldown`` only derives the slider from names that start with
``mech_``. ``read_story_4`` never reached ``mech_story``. Story, music and
epilogue therefore explicitly get ``mech_story_<level>``,
``mech_music_<level>`` and ``mech_story_epilogue`` - one bucket per level, as
MechDisplayButton already has via its ID today.

ONE PITFALL, named openly: ``mech_story`` is set to 5, exactly the fallback
rule. For story and epilogue only the ARGUMENT therefore proves the right
slider, not the value. The value check on refusal carries weight for donate
(10), display (3) and music (8).

WHERE THE BRAKE SITS: after the check "mech system disabled" (that is an
information message, not a work call) and before the ``defer`` - the refusal
therefore goes out via ``response.send_message``.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import (EpilogueButton, MechDisplayButton, MechDonateButton,
                             MechPrivateDonateButton, MechPrivateHistoryButton,
                             PlaySongButton, ReadStoryButton)
from services.infrastructure.spam_protection_service import SpamProtectionService
from tests.spec import is_not_awaitable_error

SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"
USER = 5522
CHANNEL = 88
LEVEL = 4
NOW = 90_000.0

# Name -> (builder, expected key, default value of the slider)
BUTTONS = {
    "donate": (lambda cog: MechDonateButton(cog, CHANNEL), f"mech_donate_{CHANNEL}", 10),
    "display": (lambda cog: MechDisplayButton(cog, LEVEL, str(LEVEL), True), f"mech_display_{LEVEL}", 3),
    "story": (lambda cog: ReadStoryButton(cog, LEVEL), f"mech_story_{LEVEL}", 5),
    "song": (lambda cog: PlaySongButton(cog, LEVEL), f"mech_music_{LEVEL}", 8),
    "epilogue": (lambda cog: EpilogueButton(cog), "mech_story_epilogue", 5),
}
# These four check "mech system disabled?" first - MechDonateButton does not.
WITH_DISABLED_CHECK = ["display", "story", "song", "epilogue"]


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


def _interaction():
    interaction = MagicMock()
    interaction.user.id = USER
    interaction.user.name = "tester"
    interaction.channel.id = CHANNEL
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.followup.send = AsyncMock()
    return interaction


async def _press(button, service, disabled=False):
    interaction = _interaction()
    with patch(SPAM_PATH, return_value=service), \
            patch("cogs.control_ui.is_donations_disabled", return_value=disabled):
        try:
            await button.callback(interaction)
        except TypeError as e:
            # ONLY the not-awaitable TypeError, from deep down AFTER the brake (cog methods
            # on a MagicMock) - reasoning as in
            # test_mech_buttons_brake_through_the_service.py. The tests then
            # assert POSITIVELY; an error in the brake would show up as an empty
            # recording.
            if not is_not_awaitable_error(e):
                raise
    return interaction


def test_the_keys_reach_their_slider(tmp_path):
    """Safeguard: the chosen names must arrive at the right slider via the
    prefix logic - otherwise the fix would brake by the fallback rule and the
    slider would stay dead."""
    service = SpamProtectionService(config_dir=str(tmp_path))
    assert service.get_button_cooldown("does_not_exist") == 5, "fallback rule changed"
    for name, (_build, key, value) in BUTTONS.items():
        assert service.get_button_cooldown(key) == value, (
            f"{name}: {key!r} returns {service.get_button_cooldown(key)} "
            f"instead of {value}."
        )
    for name, (build, _key, _value) in BUTTONS.items():
        assert build(MagicMock()).custom_id, f"{name}: button built without an ID"


@pytest.mark.parametrize("name", list(BUTTONS))
@pytest.mark.asyncio
async def test_the_service_is_asked_and_recorded(tmp_path, name):
    """THE FINDING: the button does not ask the service."""
    build, key, _value = BUTTONS[name]
    service = _service(tmp_path)

    await _press(build(MagicMock()), service)

    assert service.asked == [(USER, key)], (
        f"{name}: is_on_cooldown was not called with {key!r} but with "
        f"{service.asked!r}. The slider in the panel moves nothing."
    )
    assert service.recorded == [(USER, key)]


@pytest.mark.parametrize("name", list(BUTTONS))
@pytest.mark.asyncio
async def test_the_second_press_is_refused(tmp_path, monkeypatch, name):
    """THE FINDING, effect - with a frozen clock so that the stated remaining
    time is exactly the slider value."""
    # monotonic, not time: the spam-protection service reads time.monotonic()
    # at all three of its clock sites (a wall-clock correction must not brake
    # every button). Freezing time.time here therefore froze nothing, and the
    # assertion below held only because almost no real time passes between
    # add_user_cooldown and the press - under the load of a full group run it
    # stopped holding. A test that is green by luck is what this file exists
    # to catch.
    monkeypatch.setattr(time, "monotonic", lambda: NOW)
    build, key, value = BUTTONS[name]
    service = _service(tmp_path)
    service._real.add_user_cooldown(USER, key)
    cog = MagicMock()

    interaction = await _press(build(cog), service)

    sender = interaction.response.send_message
    sender.assert_awaited_once()
    assert sender.await_args.args, f"{name}: refusal without text"
    message = sender.await_args.args[0]
    assert "before using this button again" in message, f"{name}: {message!r}"
    assert f"wait {value:.1f} more" in message, (
        f"{name}: the refusal does not state the remaining time {value:.1f} s: {message!r}"
    )
    assert sender.await_args.kwargs.get("ephemeral") is True, (
        f"{name}: the refusal appears for EVERYONE in the channel."
    )
    # Nothing may continue after the refusal. defer alone does not catch
    # that: MechDonateButton hands over to the cog without defer - the
    # mutation probe initially let exactly this pass-through go unnoticed.
    interaction.response.defer.assert_not_awaited()
    assert cog.mock_calls == [], f"{name}: continued after the refusal: {cog.mock_calls!r}"


@pytest.mark.asyncio
async def test_the_private_donate_button_brakes_with_the_public_one(tmp_path):
    """It forwards to MechDonateButton and shares its bucket."""
    service = _service(tmp_path)

    await _press(MechPrivateDonateButton(MagicMock(), CHANNEL), service)

    assert service.asked == [(USER, f"mech_donate_{CHANNEL}")], service.asked


@pytest.mark.asyncio
async def test_the_private_history_button_already_brakes_today(tmp_path):
    """Scope: it was counted among the "ten" but brakes via the forwarding
    to MechHistoryButton. If the forwarding is dropped it becomes unbraked -
    that should be noticed."""
    service = _service(tmp_path)
    cog = MagicMock()
    cog._start_interaction = AsyncMock(return_value=True)

    await _press(MechPrivateHistoryButton(cog, CHANNEL), service)

    assert service.asked == [(USER, f"mech_history_{CHANNEL}")], service.asked


@pytest.mark.parametrize("name", WITH_DISABLED_CHECK)
@pytest.mark.asyncio
async def test_disabled_mech_system_uses_no_quota(tmp_path, name):
    """Scope: the "mech system disabled" message comes BEFORE the brake
    and does not count towards the minute window."""
    build, _key, _value = BUTTONS[name]
    service = _service(tmp_path)

    interaction = await _press(build(MagicMock()), service, disabled=True)

    assert service.recorded == []
    assert "disabled" in interaction.response.send_message.await_args.args[0]


@pytest.mark.parametrize("name", list(BUTTONS))
@pytest.mark.asyncio
async def test_disabled_spam_protection_brakes_nothing(tmp_path, name):
    """Scope: the operator can switch the protection off - then nothing is
    asked or recorded."""
    build, _key, _value = BUTTONS[name]
    service = _service(tmp_path)

    with patch.object(service._real, "is_enabled", return_value=False):
        await _press(build(MagicMock()), service)

    assert service.asked == [] and service.recorded == []

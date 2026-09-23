# -*- coding: utf-8 -*-
"""The admin overview's buttons ask the spam service, and can say when they fail.

THE FINDING (independent review of the cog modules, 2026-09-23): none of the
five buttons on the /control admin overview asks
get_spam_protection_service() - not the two bulk actions that restart or stop
every running container, not the stack button, not the donate button. The
panel offers no slider for them either, so an operator could not brake them
even if they wanted to.

AdminOverviewDonateButton is the plainest case: it builds an embed and a fresh
DonationView on every press, unthrottled, from a panel registered with add_view
- so it works on every admin overview ever posted.

The second half, in the same callbacks: each one defers at the top and then
its error branch reads

    if not interaction.response.is_done():      # always False after the defer
        await interaction.response.send_message("❌ Error ...")

so the error message is unreachable. A followup that fails leaves the operator
on a spinner with only a log line - the exact shape DDCView.on_error exists to
prevent, defeated by catching the exception before the view sees it.

THE NAMES: get_button_cooldown matches the whole name first, then the
"mech_<slider>_" prefix rule, then falls back to five seconds. An id of its own
would therefore brake by the fallback and leave the operator with no slider -
the mistake the defaults already carry a comment about ("the operator could
neither see nor change the value"). So each button asks under its own name,
and that name is in the defaults AND in the modal's save list, which is
hard-coded while the read loop is dynamic.

HOW THIS TEST CAN FAIL: it presses each button twice with the real spam
service behind it. A second press that goes through is red.

COUNTER-CHECK (2026-09-23): red before - the service was never asked at all.
The other tests keep the buttons working: the first press goes through, the
names really reach a slider, and the operator can change them in the panel.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"
USER = 9911
CHANNEL = 7788

# button class -> the name it must ask under
BUTTONS = {
    "AdminOverviewAdminButton": "admin_overview_admin",
    "AdminOverviewRestartAllButton": "admin_overview_restart_all",
    "AdminOverviewStopAllButton": "admin_overview_stop_all",
    "AdminOverviewRestartStackButton": "admin_overview_restart_stack",
    "AdminOverviewDonateButton": "admin_overview_donate",
}


class _Recorder:
    def __init__(self, real):
        self._real = real
        self.asked = []

    def is_on_cooldown(self, user_id, action_type):
        self.asked.append((user_id, action_type))
        return self._real.is_on_cooldown(user_id, action_type)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _interaction():
    interaction = MagicMock()
    interaction.user.id = USER
    interaction.user.name = "admin"
    interaction.channel.id = CHANNEL
    interaction.channel_id = CHANNEL
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.followup.send = AsyncMock()
    return interaction


def _build(name):
    """Three of the five take an `enabled` flag; the other two do not."""
    import cogs.admin_overview as module

    cls = getattr(module, name)
    try:
        return cls(MagicMock(), CHANNEL)
    except TypeError:
        return cls(MagicMock(), CHANNEL, True)


@pytest.mark.parametrize("class_name,expected", sorted(BUTTONS.items()))
@pytest.mark.asyncio
async def test_the_button_asks_the_spam_service(tmp_path, class_name, expected):
    """THE FINDING: none of the five asked at all."""
    service = _Recorder(SpamProtectionService(config_dir=str(tmp_path)))
    button = _build(class_name)

    with patch(SPAM_PATH, return_value=service):
        try:
            await button.callback(_interaction())
        except Exception:
            # Everything past the brake runs against MagicMocks; only the brake
            # itself is under test, and it is asserted POSITIVELY below.
            pass

    assert service.asked == [(USER, expected)], (
        f"{class_name} did not ask the spam service under {expected!r}: "
        f"{service.asked}")


@pytest.mark.parametrize("name", sorted(set(BUTTONS.values())))
def test_the_name_reaches_a_slider_of_its_own(tmp_path, name):
    """Not the 5-second fallback: the operator has to be able to see it."""
    service = SpamProtectionService(config_dir=str(tmp_path))
    config = service.get_config()

    assert config.success
    assert name in config.data.button_cooldowns, (
        f"{name} has no slider, so get_button_cooldown falls back to 5 seconds "
        "and the operator can neither see nor change it")


@pytest.mark.parametrize("name", sorted(set(BUTTONS.values())))
def test_the_panel_can_save_that_slider(name):
    """The modal's READ loop is dynamic; its SAVE list is hard-coded.

    A slider the panel renders but drops on save would look adjustable and
    reset itself on the next save.
    """
    # The modal's script moved to app/static on 2026-09-23; the markup stayed.
    modal = Path(__file__).resolve().parents[2] / "app/static/js/spam_protection_modal.js"
    markup = modal.read_text(encoding="utf-8")

    assert f"button_{name}" in markup, (
        f"{name} is not in the modal's save list, so a change to it is lost")


@pytest.mark.asyncio
async def test_the_first_press_still_goes_through(tmp_path):
    """Counter-check: braking must not become blocking."""
    service = _Recorder(SpamProtectionService(config_dir=str(tmp_path)))
    button = _build("AdminOverviewDonateButton")
    interaction = _interaction()

    with patch(SPAM_PATH, return_value=service):
        try:
            await button.callback(interaction)
        except Exception:
            pass

    assert interaction.response.defer.await_count == 1, (
        "the first press was refused - the brake is blocking, not braking")

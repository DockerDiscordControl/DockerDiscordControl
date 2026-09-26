# -*- coding: utf-8 -*-
"""The mech details button must brake - and have a slider in the panel.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision. The BEHAVIOUR CHANGE (unbraked mech buttons
brake) has been decided: "Yes, let the ten brake too".

THE FINDING. ``MechDetailsButton`` (``mech_details_<channel>``) does not ask the
spam service. Unlike the five buttons from commit 41faf4b there is also NO
slider here: no default value, no panel field, no catalog entry. Only building
in the brake would mean braking silently by the 5-second fallback rule - a
value the operator sees nowhere. That was exactly the finding for
admin/tasks/task_delete (commit 727324f).

WHY THE EXISTING CONTRACT DOES NOT CATCH IT: test_requested_
cooldown_keys_exist.py only sees literal keys; this button
asks via ``self.custom_id``. That is stated there as a limit in the header text.

THE DEFAULT IS 5, as for the related history button (mech_history). A TRAP,
named openly: 5 is also the fallback rule. A VALUE check could therefore not
distinguish whether the slider takes effect or the fallback rule. The slider
is proven here by the ARGUMENT, the default entry, the panel field and the
save block - each separately.
"""

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import MechDetailsButton
from services.infrastructure.spam_protection_service import SpamProtectionService
from tests.spec import is_not_awaitable_error

PROJECT = Path(__file__).resolve().parents[2]
# The scripts and styles moved out of the templates into app/static on
# 2026-09-23: 4,215 lines of JavaScript and CSS were inline in templates
# the panel includes, and those pages are sent Cache-Control: no-cache, so
# all of it crossed the wire on every load. The markup stayed put.
# The modal's SCRIPT moved to app/static on 2026-09-23 and its MARKUP stayed,
# and this file asks about both - so it reads both.
SCRIPT = PROJECT / "app" / "static" / "js" / "spam_protection_modal.js"
MARKUP = PROJECT / "app" / "templates" / "_spam_protection_modal.html"


class _Both:
    """The modal as one text: the markup and the script it drives."""

    @staticmethod
    def read_text(encoding="utf-8"):
        return (MARKUP.read_text(encoding=encoding)
                + SCRIPT.read_text(encoding=encoding))


TEMPLATE = _Both
SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"
USER = 7733
CHANNEL = 99
KEY = f"mech_details_{CHANNEL}"
NOW = 95_000.0


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


async def _press(service, cog=None):
    interaction = MagicMock()
    interaction.user.id = USER
    interaction.user.name = "tester"
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.followup.send = AsyncMock()
    button = MechDetailsButton(cog if cog is not None else MagicMock(), CHANNEL)
    with patch(SPAM_PATH, return_value=service):
        try:
            await button.callback(interaction)
        except TypeError as e:
            # Reasoning as in test_mech_buttons_brake_through_the_service.py.
            if not is_not_awaitable_error(e):
                raise
    return interaction


def test_the_button_carries_the_expected_id():
    """Safeguard: EXACT value, not mere existence."""
    assert MechDetailsButton(MagicMock(), CHANNEL).custom_id == KEY


def test_mech_details_is_in_the_defaults(tmp_path):
    """THE FINDING, slider first stage: without an entry only the fallback rule."""
    defaults = SpamProtectionService(config_dir=str(tmp_path))._get_default_config().button_cooldowns
    assert defaults.get("mech_details") == 5, (
        f"mech_details is missing from the defaults ({sorted(defaults)}) - the button "
        "braked by the invisible fallback rule."
    )


def test_mech_details_has_a_panel_field():
    """THE FINDING, slider second stage - with the default's start value.

    No other test compares per-button panel start values with the defaults
    (test_default_values_do_not_contradict only checks the
    per-minute limits). A deviating start value would show the operator a number
    that is not used for braking until he saves for the first time.
    """
    assert 'id="button_mech_details" value="5"' in TEMPLATE.read_text(encoding="utf-8")


def test_mech_details_survives_saving():
    """THE FINDING, slider third stage: whatever the save does not write
    drops out of the configuration on the first click on Save.

    RE-AIMED 2026-09-26. It used to cut the save's enumeration out of the
    script and look for the name in it. There is no enumeration any more -
    the save reads the dialog's own fields - so what makes a slider survive
    is now exactly that it HAS a field, which is what this asks.
    """
    assert 'id="button_mech_details"' in MARKUP.read_text(encoding="utf-8"), \
        "mech_details has no field, so nothing saves it"
    assert "readCooldowns(" in SCRIPT.read_text(encoding="utf-8"), \
        "the save no longer reads the dialog's fields"


@pytest.mark.asyncio
async def test_the_service_is_asked_and_noted(tmp_path):
    """THE FINDING: the button does not ask the service."""
    service = _service(tmp_path)

    await _press(service)

    assert service.asked == [(USER, KEY)], (
        f"is_on_cooldown was not called with {KEY!r}, but "
        f"{service.asked!r}."
    )
    assert service.noted == [(USER, KEY)]


@pytest.mark.asyncio
async def test_the_second_press_is_refused(tmp_path, monkeypatch):
    """THE FINDING, effect - before the defer, visible only to the presser,
    and nothing else runs afterwards."""
    # monotonic, not time: the spam-protection service reads time.monotonic()
    # at all three of its clock sites (a wall-clock correction must not brake
    # every button). Freezing time.time here therefore froze nothing, and the
    # assertion below held only because almost no real time passes between
    # add_user_cooldown and the press - under the load of a full group run it
    # stopped holding. A test that is green by luck is what this file exists
    # to catch.
    monkeypatch.setattr(time, "monotonic", lambda: NOW)
    service = _service(tmp_path)
    service._real.add_user_cooldown(USER, KEY)
    cog = MagicMock()

    interaction = await _press(service, cog)

    sender = interaction.response.send_message
    sender.assert_awaited_once()
    message = sender.await_args.args[0]
    assert "before using this button again" in message, message
    assert "wait 5.0 more" in message, message
    assert sender.await_args.kwargs.get("ephemeral") is True
    interaction.response.defer.assert_not_awaited()
    assert cog.mock_calls == []


@pytest.mark.asyncio
async def test_disabled_spam_protection_brakes_nothing(tmp_path):
    """Delimitation: disabled means neither asking nor noting."""
    service = _service(tmp_path)

    with patch.object(service._real, "is_enabled", return_value=False):
        await _press(service)

    assert service.asked == [] and service.noted == []


def test_the_panel_field_has_a_label():
    """THE FINDING, slider fourth stage: the label must be in the catalog.

    The catalog parity (test_pkg_d2_frontend_csrf_i18n.py) only checks that
    all languages have THE SAME keys; its search pattern for templates
    excludes Jinja's ``_t(...)``. If the key were missing equally everywhere,
    the panel would show the raw key - and no test would notice.
    """
    import json
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "_t('web.spam.button_mech_details')" in template
    catalog = json.loads((PROJECT / "locales" / "en.json").read_text(encoding="utf-8"))
    assert catalog.get("web.spam.button_mech_details") == "Mech Details"

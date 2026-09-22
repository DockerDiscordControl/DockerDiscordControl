# -*- coding: utf-8 -*-
"""Four more buttons must brake through the spam service, not on the object.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. Four buttons only fetch the DURATION from the service and store
their timestamp as an ATTRIBUTE ON THEMSELVES
(``setattr(self, f'_last_click_{user_id}', ...)``)::

    InfoDropdownButton    control_ui.py:1425            "info"
    AdminButton           control_ui.py:1791            "admin"
    HelpButton            control_ui.py:2102            "help"
    TaskManagementButton  status_info_integration.py:1182  "tasks"

``is_on_cooldown`` and ``add_user_cooldown`` are never called. The
PER-MINUTE LIMIT from the panel therefore does not apply to these four - it
counts in ``add_user_cooldown``, and they never get there.

THE STORAGE IS ALSO VOLATILE: the attribute hangs on the button object. When
the view is rebuilt - and that happens on every update - the lock is gone.
So the protection only holds as long as the same object lives.

TAKEN ALONG, because it concerns the same line: all four currently send an
UNTRANSLATED f-string (``f"⏰ Please wait ... seconds."``). The tree contains
nine such places against seven translated ones - the untranslated form is the
majority at the home-made places. The switch to the house pattern uses the
existing catalog entry.

NO NEW KEYS: "info", "admin", "help" and "tasks" already exist in the
defaults. Neither the panel nor the catalogs are affected - unlike the
three info buttons before.

WHY THE ARGUMENT IS CHECKED HERE AND NOT THE VALUE: "admin", "help" and
"tasks" are all set to 5 - and 5 is also the fallback rule for UNKNOWN names
(``get_button_cooldown:186``). A wrong key would thus return the same number.
A value check would be blunt here; adding it later would seemingly sharpen the
test and would not.

A GAP THAT ONLY THE MUTATION PROBE REVEALED: the first version of this
test checked ``assert_awaited_once``, the presence of a text and its
wording - but NOT ``ephemeral``. The mutation "ephemeral=True ->
False" therefore stayed green. A refusal without ``ephemeral`` appears for
EVERYONE in the channel; the brake would then itself create the noise it is
meant to prevent. Added after the probe had revealed the gap - a test that
cannot fail is not a test.

THE SAME PROBE FOUND A SECOND GAP: the construction guard only asserted
``assert button.custom_id`` - i.e. mere existence. A falsified id
(``help_button_5`` -> ``helpbutton_5``) left it untouched. Both cases show
the same thing: what is not EXPLICITLY nailed down here is not checked, even
if the test name promises it. Now the exact id is in the test, and the
expected values come from the source (``task_management_`` interpolates
``docker_name``, not the display name - measured, not guessed).

TRAPS OF THE FIXTURE, named in advance:

1. ``followup.send`` is used by the refusal AND the deep path. A mere
   ``assert_awaited_once`` would thus be satisfied even without a brake. Hence
   the WORDING: today "Please wait ... seconds.", after the fix the catalog
   text "... more seconds before using this button again."
2. All four acknowledge FIRST (``defer``) and brake AFTERWARDS - measured.
   A test that expects the brake before the defer would come to nothing.
3. The service is a REAL ``SpamProtectionService`` on ``tmp_path``, only
   passed through for recording.

A PREDICTION OF MINE DID NOT COME TRUE, and it belongs here because the
mistake is more instructive than the result.

I had announced that after the switch
``test_admin_button_unauthorized_uses_followup``
(``tests/unit/audit_2026_09/test_pkg_b_control_ui.py:113``) would break: it
runs with a LIVE service, the preceding ``..._not_found_on_followup_is_caught``
would enter a timestamp for the same user id (42), and because the service is
a module singleton, this state would survive from test to test.

Measured: **564 green, no break.** The chain was right in every link except
the premise. Both tests set ``is_user_admin.return_value = False``,
and ``AdminButton.callback`` checks the AUTHORIZATION (:1783) BEFORE the
brake block (:1790). Whoever is refused there never reaches the brake -
nothing is entered, and the following test cannot run into a lock.

I had measured both myself beforehand and noted them in the section "TRAPS OF
THE FIXTURE"; that is exactly why ``_press`` replaces the admin service with
``is_user_admin = True``. So my prediction contradicted my own
measurement. An argument can be right in every step and still wrong
if its premise has already been refuted elsewhere.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.control_ui import AdminButton, HelpButton, InfoDropdownButton
from cogs.status_info_integration import TaskManagementButton
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"
USER = 5521
CHANNEL = 5
CONTAINER = {"docker_name": "probe", "name": "Probe container"}

# class -> (construction, expected action name)
BUTTONS = [
    (InfoDropdownButton, "channel", "info"),
    (AdminButton, "channel", "admin"),
    (HelpButton, "channel", "help"),
    (TaskManagementButton, "container", "tasks"),
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


def _build(button_class, construction):
    cog = MagicMock()
    if construction == "channel":
        return button_class(cog, CHANNEL)
    return button_class(cog, CONTAINER)


def _interaction():
    interaction = MagicMock()
    interaction.user.id = USER
    interaction.user.name = "tester"
    interaction.channel.id = CHANNEL
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done.return_value = True
    interaction.followup.send = AsyncMock()
    return interaction


async def _press(button, service):
    """Presses the button with a replaced spam service AND an allowed admin.

    The admin replacement is not decoration: ``AdminButton.callback`` checks the
    authorization at :1783 and returns at :1785 - BEFORE the brake block.
    Without this replacement the callback never reaches the brake, and the tests
    would be red without saying anything about the brake; after the fix they
    would stay red. Measured, after exactly that had been noticed.

    The pattern is taken from tests/unit/audit_2026_09/test_pkg_b_control_ui.py,
    not invented.
    """
    interaction = _interaction()
    admin_service = MagicMock()
    admin_service.is_user_admin.return_value = True
    with patch(SPAM_PATH, return_value=service), \
            patch("services.admin.admin_service.get_admin_service",
                  return_value=admin_service):
        await button.callback(interaction)
    return interaction


def test_the_four_buttons_can_be_built():
    """Safeguard against a blunt tool - green before and after the fix.

    The EXACT id is checked, not mere existence: the first version only
    asserted ``assert button.custom_id`` and therefore could not fire at
    all - a falsified id satisfies that effortlessly. The mutation probe
    showed this.
    """
    expected = {
        InfoDropdownButton: f"info_button_{CHANNEL}",
        AdminButton: f"admin_button_{CHANNEL}",
        HelpButton: f"help_button_{CHANNEL}",
        TaskManagementButton: f"task_management_{CONTAINER['docker_name']}",
    }
    for button_class, construction, _name in BUTTONS:
        button = _build(button_class, construction)
        assert button.custom_id == expected[button_class], (
            f"{button_class.__name__} carries the id {button.custom_id!r} instead of "
            f"{expected[button_class]!r}."
        )


def test_three_of_the_four_keys_are_at_the_fallback_value(tmp_path):
    """Second safeguard - it records what can NOT be checked here.

    "admin", "help" and "tasks" are set to 5, and 5 is also the fallback
    rule for unknown names. So the VALUE cannot tell whether the right key
    is queried - the tests below check the ARGUMENT. If this changes here,
    the tests may be sharpened.
    """
    service = SpamProtectionService(config_dir=str(tmp_path))

    assert service.get_button_cooldown("does_not_exist") == 5
    assert service.get_button_cooldown("info") == 3
    for name in ("admin", "help", "tasks"):
        assert service.get_button_cooldown(name) == 5, (
            f"{name!r} is no longer at 5 - then a value check is possible."
        )


@pytest.mark.parametrize("button_class,construction,name", BUTTONS, ids=lambda x: str(x))
@pytest.mark.asyncio
async def test_the_service_is_asked_and_noted(tmp_path, button_class, construction, name):
    """THE FINDING: the stateful methods are never called."""
    service = _service(tmp_path)
    button = _build(button_class, construction)

    await _press(button, service)

    assert service.asked == [(USER, name)], (
        f"{button_class.__name__}: is_on_cooldown was not called with {name!r}, "
        f"but {service.asked!r}. The button brakes past the service and "
        "does not count towards the per-minute limit."
    )
    assert service.noted == [(USER, name)], (
        f"{button_class.__name__}: The accepted press was not noted "
        f"({service.noted!r})."
    )


@pytest.mark.parametrize("button_class,construction,name", BUTTONS, ids=lambda x: str(x))
@pytest.mark.asyncio
async def test_the_second_press_is_refused(tmp_path, button_class, construction, name):
    """THE FINDING, effect - and the message must be translated."""
    service = _service(tmp_path)
    button = _build(button_class, construction)
    service.add_user_cooldown(USER, name)
    service.noted.clear()

    interaction = await _press(button, service)

    interaction.followup.send.assert_awaited_once()
    args = interaction.followup.send.await_args.args
    assert args, (
        f"{button_class.__name__}: The refusal carries no text - that is how the "
        "deep path calls, not the brake."
    )
    assert "before using this button again" in args[0], (
        f"{button_class.__name__}: What was sent was not the catalog text, but "
        f"{args[0]!r}. The untranslated f-string reaches every user "
        "in English, whatever language he has set."
    )
    assert interaction.followup.send.await_args.kwargs.get("ephemeral") is True, (
        f"{button_class.__name__}: The refusal is not restricted to the presser "
        "and therefore appears for EVERYONE in the channel. A brake that itself creates "
        "noise is worse than none."
    )


@pytest.mark.parametrize("button_class,construction,name", BUTTONS, ids=lambda x: str(x))
@pytest.mark.asyncio
async def test_the_volatile_storage_on_the_object_is_gone(tmp_path, button_class, construction, name):
    """THE FINDING, third part: no lock that dies with the object."""
    service = _service(tmp_path)
    button = _build(button_class, construction)

    await _press(button, service)

    leftovers = [a for a in dir(button) if a.startswith("_last_click_")]
    assert not leftovers, (
        f"{button_class.__name__} still stores {leftovers} on the object. This lock "
        "is gone on the next rebuild of the view."
    )

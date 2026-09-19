# -*- coding: utf-8 -*-
"""The log button must brake through the spam service, not bypass it via the cog.

NO ``@covers`` marker: that would be a new guarantee, and those are the
operator's decision.

THE FINDING. ``DebugLogsButton.callback`` (``status_info_integration.py:684-705``)
only fetches the DURATION from the service (``get_button_cooldown("logs")``)
and then does the bookkeeping itself: timestamps under ``button_logs_<user>``
in ``self.cog._button_cooldowns``. The stateful methods of the service -
``is_on_cooldown`` and ``add_user_cooldown`` - are never called.

WHAT THE OPERATOR SEES OF IT: the **per-minute limit** from the panel does not
apply to this button. It counts in ``add_user_cooldown``, and since this path
never arrives there, it is not counted. The operator sets "at most 30 buttons
per minute", and this button ignores it - while the cooldown next to it works
dutifully. Exactly the mix nobody notices.

THIS IS ONE OF THIRTEEN PLACES, and deliberately the first: it is the only one
of the four cog bookkeepings that needs NO new key - ``logs`` already exists
with 10 seconds. This lets the conversion pattern be proven completely here
before it is applied to places that additionally touch panel fields and 40
catalogs.

WHAT DOES NOT CHANGE FOR THE USER: the key stays ``logs``, the duration stays
10 seconds, the bucket stays exclusive to this button (the action name
``logs`` is not used as a lock anywhere else - measured). The only new thing
is that the press is RECORDED in the service and thus counts towards the
per-minute limit.

THREE PITFALLS IN THE FIXTURE, named in advance:

1. In the test the cog must NOT be a ``MagicMock`` with auto-generated
   attributes. Today's code asks ``hasattr(self.cog, '_button_cooldowns')``,
   and a MagicMock always answers that with true - the button would never
   refuse, and the test would check the mock instead of the code. Hence a REAL
   dictionary.
2. ``callback`` wraps its whole body in ``except Exception`` (``:782``). An
   error deep down is thus SWALLOWED. A test that only checks for the absence
   of errors would be hollowly green. That is why only POSITIVE assertions are
   made here: the refusal must have been sent.
3. The service is a REAL ``SpamProtectionService`` on ``tmp_path``, only passed
   through for recording. A pure mock could return any number and would not
   show whether the right path is taken.

SCOPE: the replacement is done on the MODULE PATH
(``services.infrastructure.spam_protection_service.get_spam_protection_service``),
because the import only happens INSIDE the method - a replacement on the
module of the call site would hit nothing.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.status_info_integration import DebugLogsButton
from services.infrastructure.spam_protection_service import SpamProtectionService

SPAM_PATH = "services.infrastructure.spam_protection_service.get_spam_protection_service"
USER = 8123
CONTAINER = {"docker_name": "probe"}


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


def _cog():
    """Cog with a REAL dictionary - see pitfall 1 in the header."""
    cog = MagicMock()
    cog._button_cooldowns = {}
    return cog


def _interaction():
    interaction = MagicMock()
    interaction.user.id = USER
    interaction.channel.id = 7
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


async def _press(button, service):
    interaction = _interaction()
    with patch(SPAM_PATH, return_value=service):
        await button.callback(interaction)
    return interaction


def test_the_button_can_be_built():
    """Safeguard against a blunt tool - green before and after the fix."""
    button = DebugLogsButton(_cog(), CONTAINER)

    assert button.custom_id == "debug_logs_probe"
    assert button.container_name == "probe"


def test_the_cooldown_for_logs_is_set_at_all(tmp_path):
    """Second safeguard: the assertions below are only worth something if
    ``logs`` has its own value, different from the fallback rule.

    The fallback rule is 5 (get_button_cooldown:186). If logs were also 5, it
    would be impossible to tell whether the key is found at all.
    """
    service = SpamProtectionService(config_dir=str(tmp_path))

    assert service.get_button_cooldown("logs") == 10
    assert service.get_button_cooldown("does_not_exist") == 5


@pytest.mark.asyncio
async def test_the_service_is_asked_at_all(tmp_path):
    """THE FINDING: the stateful methods are never called."""
    service = _service(tmp_path)
    button = DebugLogsButton(_cog(), CONTAINER)

    await _press(button, service)

    assert service.asked == [(USER, "logs")], (
        f"is_on_cooldown was not called with (USER, 'logs') but with "
        f"{service.asked!r}. The button keeps its cooldown past the service "
        "- and so does not count towards the per-minute limit."
    )
    assert service.recorded == [(USER, "logs")], (
        f"The accepted press was not recorded in the service ({service.recorded!r}). "
        "Without add_user_cooldown it does not count towards the per-minute limit."
    )


@pytest.mark.asyncio
async def test_the_second_press_is_refused(tmp_path):
    """THE FINDING, effect: what is in the service must brake the button."""
    service = _service(tmp_path)
    button = DebugLogsButton(_cog(), CONTAINER)
    service.add_user_cooldown(USER, "logs")
    service.recorded.clear()

    interaction = await _press(button, service)

    interaction.followup.send.assert_awaited_once()
    args = interaction.followup.send.await_args.args
    kwargs = interaction.followup.send.await_args.kwargs

    # THREE assertions, and each one individually necessary - measured, not guessed:
    # The success path calls followup.send(embed=…, view=…, ephemeral=True), i.e.
    # WITHOUT a positional argument; a mere assert_awaited_once would therefore
    # also be satisfied if nothing was refused but the log was delivered. On the
    # deep path there are also two followup.send WITH positional text
    # ("Could not retrieve debug logs"), hence the wording in addition.
    assert kwargs.get("embed") is None, (
        "An embed was sent - that is the success path with the logs, not the "
        "refusal. So the button did not brake."
    )
    assert args, (
        f"The refusal carries no text as a positional argument: {kwargs!r}. "
        "That is how the success path calls, not the brake."
    )
    assert "before using this button again" in args[0], (
        f"The sent message is not the cooldown refusal: {args[0]!r}"
    )
    assert kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_the_own_bookkeeping_on_the_cog_is_dropped(tmp_path):
    """THE FINDING, third half: one store instead of two.

    If the cog store remained, the state would exist twice - and the next fix
    would again maintain only one of the two places.
    """
    service = _service(tmp_path)
    cog = _cog()
    button = DebugLogsButton(cog, CONTAINER)

    await _press(button, service)

    assert cog._button_cooldowns == {}, (
        f"The button still writes into cog._button_cooldowns "
        f"({cog._button_cooldowns!r}) - the same information in two places."
    )


@pytest.mark.asyncio
async def test_with_protection_disabled_nothing_brakes(tmp_path):
    """Scope: the operator can switch the protection off."""
    service = _service(tmp_path)
    button = DebugLogsButton(_cog(), CONTAINER)

    with patch.object(service._real, "is_enabled", return_value=False):
        interaction = await _press(button, service)

    assert service.asked == []
    interaction.response.defer.assert_awaited_once()

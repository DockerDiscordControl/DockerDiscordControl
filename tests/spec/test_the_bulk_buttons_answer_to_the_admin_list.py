# -*- coding: utf-8 -*-
# @covers Z5
"""Z5 and B2 on the bulk buttons - REFUTED as a finding, pinned as the rule.

THE FINDING (review D36, pass 2, section 01 F1 and F2, twins for restart-all
and stop-all): the bulk buttons check only `is_user_admin_async(user_id)` and
never the channel's 'restart'/'stop' permission, so a registered admin can
restart or stop every container in the installation from a channel that holds
no permission at all.

That is exactly what is supposed to happen. SPEC.md **B2**: "The global admin
list exists for the status channels ... admins may also do things where
channel membership alone permits nothing", confirmed by the operator on
2026-09-16 and restated by them on 2026-09-19 with the Z5 clarification.
Adding a channel check here would refuse the operator in a status channel -
the precise regression the Z5 fix of 2026-09-16/17 caused, which had to be
undone three days later.

WHY THIS TEST EXISTS AT ALL: pass 1 found the same thing in the same file
(section 01 F1, "high") and refuted it with the same reasoning. Pass 2, which
never saw that verdict, found it again and called it critical. Two
independent readings of this code both took a documented decision for a
security hole. A decision recorded only in SPEC.md and a review document does
not stop the third reader from "fixing" it - and that fix would break the
operator's own panel. So it is written here, where the code is, and it goes
red if anyone adds the check.

WHAT IS REALLY REPAIRED HERE: the confirmation press did not re-read the
admin list. The first press checks it; the confirm button, a separate
interaction up to 30 seconds later, checked nothing at all. The Z5
clarification says the list is "read at the moment of the press, never from a
message" - so the second press has to read it too. The window is small (the
view times out at 30 s and the message is ephemeral, so only the verified
presser can even see it), and closing it costs one call.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.admin_overview as ao
from cogs.admin_overview import ConfirmRestartAllButton, ConfirmStopAllButton

ADMIN_ID = 4711
STRANGER_ID = 1234
STATUS_CHANNEL = 300          # holds no permission whatsoever


def _interaction(user_id):
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.edit_original_response = AsyncMock()
    inter.user.id = user_id
    inter.user.name = "somebody"
    inter.channel.id = STATUS_CHANNEL
    return inter


@pytest.fixture
def environment(monkeypatch):
    """One running container that allows both actions; nothing else is real."""
    acted = []

    async def _action(docker_name, action):
        acted.append((docker_name, action))
        return True

    monkeypatch.setattr(
        "services.docker_service.docker_action_service.docker_action_service_first",
        _action)
    monkeypatch.setattr(ao, "get_server_config_service", lambda: SimpleNamespace(
        get_all_servers=lambda: [{"docker_name": "nginx", "name": "nginx",
                                  "active": True,
                                  "allowed_actions": ["start", "stop", "restart"]}]))

    from services.docker_status.models import ContainerStatusResult
    running = ContainerStatusResult.success_result(
        docker_name="nginx", display_name="nginx", is_running=True,
        cpu="1%", ram="10MB", uptime="1h", details_allowed=True)
    monkeypatch.setattr(ao, "get_status_cache_service", lambda: SimpleNamespace(
        get=lambda name: {"data": running}))

    admins = {str(ADMIN_ID)}

    async def _is_admin(user_id):
        return str(user_id) in admins

    monkeypatch.setattr(ao, "get_admin_service",
                        lambda: SimpleNamespace(is_user_admin_async=_is_admin))
    return acted, admins


def _button(button_class):
    button = button_class.__new__(button_class)
    button.cog = SimpleNamespace(_bulk_operation_in_progress=False)
    button.channel_id = STATUS_CHANNEL
    return button


BUTTONS = [(ConfirmRestartAllButton, "restart"), (ConfirmStopAllButton, "stop")]


@pytest.mark.parametrize("button_class,action", BUTTONS)
async def test_an_admin_acts_in_a_channel_with_no_permission(environment, button_class, action):
    """B2, and the reason this file exists. Do not "fix" this."""
    acted, _ = environment

    await _button(button_class).callback(_interaction(ADMIN_ID))

    assert ("nginx", action) in acted, (
        f"a registered admin pressed {action}-all in a status channel and "
        f"nothing happened - SPEC.md B2 says the admin list exists for "
        f"exactly this, and the operator was once refused here for real"
    )


@pytest.mark.parametrize("button_class,action", BUTTONS)
async def test_someone_who_is_not_on_the_list_moves_nothing(environment, button_class, action):
    """The counter-case: B2 is a right for admins, not for everybody."""
    acted, _ = environment

    await _button(button_class).callback(_interaction(STRANGER_ID))

    assert acted == [], (
        f"{acted} - a user who is not on the admin list reached the bulk "
        f"{action}"
    )


@pytest.mark.parametrize("button_class,action", BUTTONS)
async def test_the_list_is_read_at_the_confirming_press(environment, button_class, action):
    """The one real repair: the second press reads the list as well.

    The admin list is read "at the moment of the press, never from a message"
    (Z5 clarification). Between opening the confirmation and confirming it,
    /removeadmin may have run.
    """
    acted, admins = environment
    admins.clear()          # removed between the two presses

    await _button(button_class).callback(_interaction(ADMIN_ID))

    assert acted == [], (
        f"{acted} - the presser was taken off the admin list before they "
        f"confirmed, and the bulk {action} ran anyway"
    )

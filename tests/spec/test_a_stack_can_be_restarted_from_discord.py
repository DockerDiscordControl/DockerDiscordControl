# -*- coding: utf-8 -*-
"""A Compose stack can be restarted from the Admin Overview (Phase 4c, part 3).

"Restart stack" uses the existing multi-container action: the Admin Overview
gets a stack button, the admin picks a stack, confirms, and the running
containers of that stack are restarted by the same routine as "Restart All"
(allowed_actions respected, a stopped container skipped, one without a
current status reported as not checked).

* the stacks are read from the status cache (compose_project) for the ACTIVE
  servers, in the server order; a container outside a stack is in none;
* the first press and the confirming press both read the admin list at the
  moment of the press (Z5), and - as for the other bulk buttons (SPEC.md
  B2) - no channel permission is asked;
* only the chosen stack's containers are touched; the stack is read again at
  the confirming press, not remembered from the first one;
* with no stack at all the button says so instead of offering an empty list;
* the button is a persistent Admin Overview button like the others
  (tests/spec/test_buttons_on_old_messages_keep_working.py lists its key).

COUNTER-CHECK (2026-09-22): red before the module existed; dropping the
stack filter at the confirming press restarts "grafana" of the other stack
and turns two tests red.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.admin_overview as ao
from services.docker_status.models import ContainerStatusResult

ADMIN_ID, STRANGER_ID, CHANNEL = 4711, 1234, 300
ALL = ["start", "stop", "restart"]


def _status(name, *, running=True, project=None):
    result = ContainerStatusResult.success_result(
        docker_name=name, display_name=name, is_running=running,
        cpu="1%", ram="10MB", uptime="1h", details_allowed=True)
    result.compose_project = project
    return {"data": result}


SERVERS = [
    {"docker_name": "db", "active": True, "allowed_actions": ALL},
    {"docker_name": "plex", "active": True, "allowed_actions": ALL},
    {"docker_name": "web", "active": True, "allowed_actions": ALL},
    {"docker_name": "worker", "active": True, "allowed_actions": ["start"]},
    {"docker_name": "cache", "active": False, "allowed_actions": ALL},
    {"docker_name": "grafana", "active": True, "allowed_actions": ALL},
]
CACHE = {
    "db": _status("db", project="blog"),
    "plex": _status("plex"),
    "web": _status("web", project="blog"),
    "worker": _status("worker", project="blog"),
    "cache": _status("cache", project="blog"),
    "grafana": _status("grafana", project="mon"),
}


@pytest.fixture
def world(monkeypatch, tmp_path):
    # An empty config directory of its own: since 2026-09-23 the button offers
    # the operator's GROUPS next to the Compose stacks, and a group left behind
    # by another test in this group run would answer "there is something to
    # offer" here. Green alone, red in the group - and for the wrong reason.
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.config import group_service

    group_service.reset_group_service()
    # Since 2026-09-23 the admin overview's buttons ask the spam service, and
    # this file presses the same button as the same user several times - the
    # second press would be refused, which is the BRAKE working, not the button
    # failing. The brake has its own test
    # (tests/spec/test_the_admin_overview_buttons_brake_too.py); here it is out
    # of the way.
    monkeypatch.setattr(
        "services.infrastructure.spam_protection_service.get_spam_protection_service",
        lambda: SimpleNamespace(is_enabled=lambda: False))
    acted = []

    async def _action(docker_name, action):
        acted.append((docker_name, action))
        return True

    monkeypatch.setattr("services.docker_service.docker_action_service.docker_action_service_first", _action)
    servers = [dict(s) for s in SERVERS]
    cache = dict(CACHE)
    monkeypatch.setattr(ao, "get_server_config_service", lambda: SimpleNamespace(get_all_servers=lambda: servers))
    monkeypatch.setattr(ao, "get_status_cache_service", lambda: SimpleNamespace(get=cache.get))
    admins = {str(ADMIN_ID)}

    async def _is_admin(user_id):
        return str(user_id) in admins

    monkeypatch.setattr(ao, "get_admin_service", lambda: SimpleNamespace(is_user_admin_async=_is_admin))
    monkeypatch.setattr(ao.asyncio, "sleep", AsyncMock())
    return SimpleNamespace(acted=acted, admins=admins, cache=cache)


def _interaction(user_id):
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.response.edit_message = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.user.id = user_id
    inter.channel.id = CHANNEL
    return inter


def _cog():
    return SimpleNamespace(_bulk_operation_in_progress=False)


def test_stacks_are_read_for_the_active_servers_in_order(world):
    from cogs.stack_restart import stacks_of

    stacks = stacks_of(SERVERS, SimpleNamespace(get=world.cache.get))
    assert list(stacks) == ["blog", "mon"]
    assert [s["docker_name"] for s in stacks["blog"]] == ["db", "web", "worker"]


async def test_the_confirming_press_restarts_only_the_chosen_stack(world):
    from cogs.stack_restart import ConfirmRestartStackButton

    inter = _interaction(ADMIN_ID)
    await ConfirmRestartStackButton(_cog(), CHANNEL, "blog").callback(inter)
    assert world.acted == [("db", "restart"), ("web", "restart")]
    embed = inter.followup.send.await_args.kwargs["embed"]
    assert "blog" in embed.title
    assert "**2**" in embed.description and "action not allowed" in embed.description


async def test_the_stack_is_read_again_at_the_confirming_press(world):
    from cogs.stack_restart import ConfirmRestartStackButton

    button = ConfirmRestartStackButton(_cog(), CHANNEL, "blog")
    world.cache["web"] = _status("web", project="other")  # recreated into another stack meanwhile
    await button.callback(_interaction(ADMIN_ID))
    assert world.acted == [("db", "restart")]


async def test_the_list_is_read_at_the_confirming_press(world):
    from cogs.stack_restart import ConfirmRestartStackButton

    button = ConfirmRestartStackButton(_cog(), CHANNEL, "blog")
    world.admins.clear()  # /removeadmin between the two presses
    inter = _interaction(ADMIN_ID)
    await button.callback(inter)
    assert world.acted == []
    assert "permission" in inter.followup.send.await_args.args[0].lower()


async def test_the_first_press_offers_the_stacks_to_an_admin_only(world):
    button = ao.AdminOverviewRestartStackButton(_cog(), CHANNEL, enabled=True)
    stranger = _interaction(STRANGER_ID)
    await button.callback(stranger)
    assert "view" not in stranger.followup.send.await_args.kwargs

    admin = _interaction(ADMIN_ID)
    await button.callback(admin)
    view = admin.followup.send.await_args.kwargs["view"]
    select = view.children[0]
    # The option's value is its position in the menu (a Compose project name may be
    # longer than the 100 characters Discord allows there); the label is the name.
    assert [o.label for o in select.options] == ["blog", "mon"]
    assert world.acted == []


async def test_without_any_stack_the_button_says_so(world):
    for name in list(world.cache):
        world.cache[name] = _status(name)
    admin = _interaction(ADMIN_ID)
    await ao.AdminOverviewRestartStackButton(_cog(), CHANNEL, enabled=True).callback(admin)
    assert "view" not in admin.followup.send.await_args.kwargs
    assert "stack" in admin.followup.send.await_args.args[0].lower()


async def test_choosing_a_stack_asks_for_confirmation(world):
    from cogs.stack_restart import ConfirmRestartStackButton, StackSelect

    select = StackSelect(_cog(), CHANNEL, {"blog": ["db", "web"], "mon": ["grafana"]})
    inter = _interaction(ADMIN_ID)
    blog = next(o.value for o in select.options if o.label == "blog")
    select._selected_values, select._interaction = [blog], inter  # what py-cord's refresh_state sets
    await select.callback(inter)
    kwargs = inter.response.edit_message.await_args.kwargs
    assert "db" in kwargs["embed"].description and "web" in kwargs["embed"].description
    confirm = [c for c in kwargs["view"].children if isinstance(c, ConfirmRestartStackButton)]
    assert confirm and confirm[0].stack == "blog"
    assert world.acted == []

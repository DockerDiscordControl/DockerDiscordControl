# -*- coding: utf-8 -*-
"""The stack menu tells the truth about names, numbers and limits (Phase 4c).

Four things the first version of the stack restart got wrong, all with data
the operator controls - Compose project names and how many containers a stack
has:

* the stack's name went into the confirmation as `**{stack}**` unescaped, so
  a project called `media_stack_01` showed up with an italic middle - the
  admin read a name that is not the one being restarted. The rest of the code
  base escapes it (cogs/overview_embeds.py does, for the same data);
* the member list was joined without a limit; past ~250 containers the
  description exceeds Discord's 4096 characters and the confirmation is
  refused, so the admin gets a generic error instead;
* a select menu holds 25 options. Stacks past the 25th were dropped with a
  line in the log and nothing on screen;
* an option's value may hold 100 characters, and the code truncated only the
  label. A longer project name made Discord refuse the whole message.

COUNTER-CHECK (2026-09-22): red before on all four - the unescaped name, the
6,000-character description, the missing notice and the over-long value.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import cogs.admin_overview as ao
from cogs.stack_restart import MAX_OPTIONS, StackSelect, offer_stacks
from services.docker_status.models import ContainerStatusResult

CHANNEL = 300


def _select(stacks):
    return StackSelect(SimpleNamespace(), CHANNEL, stacks)


def _interaction():
    inter = MagicMock()
    inter.response.defer = AsyncMock()
    inter.response.edit_message = AsyncMock()
    inter.followup.send = AsyncMock()
    inter.user.id = 1
    return inter


def _chosen(select, stack):
    inter = _interaction()
    select._selected_values, select._interaction = [stack], inter
    import asyncio

    asyncio.run(select.callback(inter))
    return inter.response.edit_message.await_args.kwargs["embed"]


def test_the_stack_name_cannot_format_the_confirmation():
    embed = _chosen(_select({"media_stack_01": ["plex"]}), "media_stack_01")
    assert r"media\_stack\_01" in embed.description


def test_a_huge_stack_still_fits_into_the_confirmation():
    members = [f"container-{i:04d}-eu-west" for i in range(400)]
    embed = _chosen(_select({"big": members}), "big")
    assert len(embed.description) <= 4096
    assert "container-0000" in embed.description and "more" in embed.description


def test_an_over_long_project_name_is_still_a_valid_option():
    long_name = "p" * 150
    select = _select({long_name: ["a"]})
    option = select.options[0]
    assert len(option.label) <= 100 and len(option.value) <= 100
    embed = _chosen(select, option.value)
    assert "p" * 20 in embed.description


@pytest.mark.asyncio
async def test_more_stacks_than_the_menu_holds_are_named_as_missing(monkeypatch):
    servers = [{"docker_name": f"c{i}", "active": True, "allowed_actions": ["restart"]}
               for i in range(MAX_OPTIONS + 5)]

    def _status(name, project):
        result = ContainerStatusResult.success_result(
            docker_name=name, display_name=name, is_running=True, cpu="1%", ram="1MB",
            uptime="1h", details_allowed=True)
        result.compose_project = project
        return {"data": result}

    cache = {s["docker_name"]: _status(s["docker_name"], f"stack{i}")
             for i, s in enumerate(servers)}
    monkeypatch.setattr(ao, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: servers))
    monkeypatch.setattr(ao, "get_status_cache_service", lambda: SimpleNamespace(get=cache.get))
    monkeypatch.setattr(ao, "get_admin_service",
                        lambda: SimpleNamespace(is_user_admin_async=AsyncMock(return_value=True)))
    inter = _interaction()

    await offer_stacks(SimpleNamespace(), CHANNEL, inter)

    kwargs = inter.followup.send.await_args.kwargs
    assert len(kwargs["view"].children[0].options) == MAX_OPTIONS
    assert "5" in kwargs["embed"].description, kwargs["embed"].description

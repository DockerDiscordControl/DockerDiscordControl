# -*- coding: utf-8 -*-
"""The info dropdown answers Discord in time, and the info keeps one budget.

THE FINDING (final check before v3.1.0, 2026-09-29). Picking a container in
the info dropdown ran the game query, the Docker lookup and the WAN address
lookup first and answered the interaction after them, with
response.edit_message. Discord allows 3 seconds. The game query alone may
use the 2.5 s budget (a server that stopped answering, before it is demoted)
- and the Docker wait after it started a FRESH 2.5 s instead of taking what
was left, so the info could take 5 s. The member saw "This interaction
failed". The ℹ️ button defers first and was not hit.

THE CONTRACT: the dropdown acknowledges (defer) before any of the lookups and
edits the original response after them; the Docker wait uses what is left of
the one budget.

HOW THIS TEST CAN FAIL: the lookups run before the acknowledgement again, or
a slow Docker daemon adds a second budget.

COUNTER-CHECK (2026-09-29): with the defer removed the first test goes red
(the answer comes after the lookup, through response.edit_message); with the
Docker wait back on the full BUDGET_SECONDS the budget test goes red.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_the_dropdown_acknowledges_before_it_looks_anything_up(monkeypatch):
    import cogs.control_ui as control_ui
    import cogs.info_extras as info_extras_module
    from cogs.control_ui import ContainerInfoDropdown

    order = []
    server = {"docker_name": "web", "display_name": "Web", "info": {}}
    monkeypatch.setattr(control_ui, "get_server_config_service", lambda: MagicMock(
        get_server_by_docker_name=lambda _name: server))
    monkeypatch.setattr("services.config.config_service.load_config", lambda: {})
    monkeypatch.setattr(control_ui, "_get_cached_channel_permission", lambda *_a: False)
    monkeypatch.setattr(control_ui, "_is_registered_admin", lambda _uid: False)

    async def _extras(_config):
        order.append("lookup")
        return info_extras_module.Extras()

    monkeypatch.setattr(info_extras_module, "info_extras", _extras)
    monkeypatch.setattr(ContainerInfoDropdown, "values", property(lambda self: ["web"]))

    interaction = MagicMock()
    interaction.response.defer = AsyncMock(side_effect=lambda *a, **k: order.append("defer"))
    interaction.response.edit_message = AsyncMock()
    interaction.edit_original_response = AsyncMock()

    dropdown = ContainerInfoDropdown(MagicMock(), [{"name": "web", "display": "Web"}])
    await dropdown.callback(interaction)

    assert order == ["defer", "lookup"], order
    interaction.edit_original_response.assert_awaited_once()
    interaction.response.edit_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_docker_wait_takes_what_is_left_of_the_budget(monkeypatch):
    import cogs.info_extras as info_extras_module
    import services.infrastructure.container_facts_service as facts_service

    monkeypatch.setattr(info_extras_module, "BUDGET_SECONDS", 0.3)

    async def _slow_game(_config):
        await asyncio.sleep(0.3)     # the game query uses the whole budget
        return None

    async def _slow_docker(_name):
        await asyncio.sleep(5)
        return None

    monkeypatch.setattr(info_extras_module, "player_list", _slow_game)
    monkeypatch.setattr(facts_service, "get_container_facts", _slow_docker)

    loop = asyncio.get_running_loop()
    started = loop.time()
    await info_extras_module.info_extras({"docker_name": "web", "allow_detailed_status": False})
    took = loop.time() - started

    assert took < 0.5, f"the info took {took:.2f} s on a 0.3 s budget"

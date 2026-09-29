# -*- coding: utf-8 -*-
"""A normal /info leaves no "interaction already acknowledged" warning.

THE FINDING (stage 4 review before v3.1.0, section 05 pass 4 F7): /info
defers first, which makes interaction.response.is_done() True - and the send
step took exactly that as the sign of a race with autocomplete: every
successful /info logged a WARNING "Interaction already acknowledged ... Using
followup instead". A real race would have looked the same as every ordinary
call.

THE CONTRACT: the warning is written only when the interaction was answered
before /info deferred it; an ordinary call sends by followup silently.

HOW THIS TEST CAN FAIL: the warning appears on an ordinary /info again, or
the answer goes missing.

COUNTER-CHECK (2026-09-29): red before the change.
"""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import cogs.slash_commands as sc


async def test_an_ordinary_info_is_answered_without_a_warning(monkeypatch, caplog):
    state = {"done": False}

    async def _defer(**kwargs):
        state["done"] = True
    response = SimpleNamespace(is_done=lambda: state["done"], defer=_defer)
    ctx = MagicMock()
    ctx.response = response
    ctx.interaction.response = response
    ctx.channel_id = 300
    ctx.author.id = 4711
    ctx.followup.send = AsyncMock()
    ctx.respond = AsyncMock()

    # /info imports it from control_helpers at the call
    monkeypatch.setattr("cogs.control_helpers._channel_has_permission",
                        lambda channel_id, key, config=None: key == "info")
    monkeypatch.setattr(sc, "get_server_config_service", lambda: SimpleNamespace(
        get_all_servers=lambda: [{"docker_name": "c1", "display_name": "c1"}]))
    monkeypatch.setattr("services.infrastructure.container_info_service.get_container_info_service",
                        lambda: SimpleNamespace(get_container_info=lambda name: SimpleNamespace(
                            success=True, data=SimpleNamespace(to_dict=lambda: {}))))
    monkeypatch.setattr("cogs.status_info_integration.StatusInfoButton._generate_info_embed",
                        AsyncMock(return_value=MagicMock()))
    cog = MagicMock()
    cog._check_spam_protection = AsyncMock(return_value=True)
    cog.config = {"channel_permissions": {}}

    with caplog.at_level(logging.WARNING):
        await sc.SlashCommandsMixin.info_command.callback(cog, ctx, "c1")

    assert ctx.followup.send.await_count == 1, "the /info answer went missing"
    assert "embed" in ctx.followup.send.await_args.kwargs, ctx.followup.send.await_args
    warned = [r.getMessage() for r in caplog.records if "already acknowledged" in r.getMessage()]
    assert not warned, f"an ordinary /info logged a race warning: {warned}"

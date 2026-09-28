# -*- coding: utf-8 -*-
"""A game server that does not answer is not shown green.

FOUND ON THE OPERATOR'S HOST (2026-09-28): the Enshrouded server had died on
16 September - its log ends there, no process listens - while its container
ran on, kept alive by a `tail -f`. For twelve days every overview showed it
🟢 online. The support check had long since marked it unreachable, and the
status loop skipped it every cycle - without telling anybody.

Now the loop marks such a container where it skips it (game_silent: running,
player count switched on, the game server marked as not answering), and every
panel draws it ⚠️ instead of 🟢 - the admin overview, the server overview and
the container's status message, which also says "Game not answering". The
header still counts it as online: the container does run.

COUNTER-CHECK (2026-09-28): with the mark removed from the enrichment, the
marking case went red; with running_lamp ignoring game_silent, the lamp case
and the three rendering cases did. The counter-cases - an answering server, an unknown
verdict, a stopped container - stayed as they were.
"""

from unittest.mock import MagicMock, patch

import pytest

import cogs.status_handlers as sh_mod
from cogs.status_handlers import StatusHandlersMixin
from services.discord.embed_helper_service import running_lamp
from services.docker_status.models import ContainerStatusResult
from tests.unit.audit_2026_09.test_r2_g4_status import (FakeStatusCache, _cog, _entry, _render_patches,
                                                        _servers)
from tests.unit.cogs.test_status_enrichment_skip import _cfg, _enrich, _query_service, _running, _support


async def test_the_status_loop_marks_a_silent_game_server():
    results = {"enshrouded": _running("enshrouded"), "valheim": _running("valheim"), "icarus": _running("icarus")}
    await _enrich(results, _cfg("enshrouded", "valheim", "icarus"), _query_service(),
                  _support({"enshrouded": False, "valheim": True, "icarus": None}))
    assert results["enshrouded"].game_silent is True
    assert results["valheim"].game_silent is False and results["valheim"].players_online == 3
    assert results["icarus"].game_silent is False, "an unknown verdict is not silence"


def test_the_lamp():
    silent = _running("x")
    silent.game_silent = True
    assert running_lamp(silent) == "⚠️"
    assert running_lamp(_running("y")) == "🟢"
    stopped = ContainerStatusResult.offline_result("z", "Z")
    stopped.game_silent = True
    assert running_lamp(stopped) == "🔴", "a stopped container is off, not silent"


def _silent_and_green():
    silent = _running("enshrouded")
    silent.game_silent = True
    return FakeStatusCache({"enshrouded": _entry(data=silent), "valheim": _entry(data=_running("valheim"))})


SERVERS = [{"docker_name": "enshrouded", "display_name": "Enshrouded"},
           {"docker_name": "valheim", "display_name": "Valheim"}]


async def _overview(builder):
    cog = _cog(_silent_and_green())
    patches = _render_patches()
    for p in patches:
        p.start()
    try:
        return await getattr(cog, builder)(SERVERS, {})
    finally:
        for p in patches:
            p.stop()


async def test_the_admin_overview_draws_it_as_a_warning():
    embed, _file, has_running = await _overview("_create_admin_overview_embed")
    assert "⚠️ Enshrouded" in embed.description and "🟢 Valheim" in embed.description
    assert "Online: 2" in embed.description, "the container does run"


async def test_the_server_overview_draws_it_as_a_warning():
    embed, _file = await _overview("_create_overview_embed_collapsed")
    assert "│ ⚠️ Enshrouded" in embed.description and "│ 🟢 Valheim" in embed.description


async def test_the_status_message_says_so():
    silent = _running("enshrouded")
    silent.game_silent = True
    mixin = StatusHandlersMixin()
    mixin.status_cache_service = FakeStatusCache({"enshrouded": _entry(data=silent)})
    mixin.pending_actions = {}
    mixin.expanded_states = {}
    mixin.cache_ttl_seconds = 75
    with patch.object(sh_mod, "get_server_config_service", return_value=_servers("enshrouded")), \
         patch.object(sh_mod, "_channel_has_permission", return_value=False), \
         patch.object(sh_mod, "ControlView", MagicMock()), \
         patch("cogs.status_info_integration.should_show_info_in_status_channel", return_value=False):
        embed, _view, running = await mixin._generate_status_embed_and_view(
            1, "Enshrouded", {"docker_name": "enshrouded"}, {"language": "en"})
    assert "⚠️ Game not answering" in embed.description and running is True

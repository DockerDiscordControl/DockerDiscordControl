# -*- coding: utf-8 -*-
"""A server that answers the info query but not the player query keeps its line.

THE FINDING (stage 4 review before v3.1.0, section 19b pass 4 F2): for
Source and Palworld the player list asked the server info and the player
names under one timeout. A server that answers A2S_INFO but not A2S_PLAYER
(host_players_show 0, a rate-limiting query proxy) made the whole port
count as failed: the info display said "player list cannot be read" and
lost the server name, game, version and port as well - while the status
line showed the count from the info query alone.

THE CONTRACT: when only the names do not come, the list still succeeds with
the count and the server's details, and says the names were not given.

HOW THIS TEST CAN FAIL: a silent or refusing player query fails the whole
list again, or the list claims to have named everyone.

COUNTER-CHECK (2026-09-30): red before the change (success False, timeout).
"""

import asyncio
from types import SimpleNamespace

import pytest

from services.infrastructure.game_query_service import GameQueryRequest, GameQueryService
from tests.spec.test_every_container_shows_who_plays import _fake_opengsq


async def _silent():
    await asyncio.sleep(10)


async def _refused():
    raise ConnectionResetError("player query refused")


@pytest.mark.parametrize("names_query", [_silent, _refused], ids=["silent", "refused"])
def test_source_keeps_the_count_and_the_name(monkeypatch, names_query):
    class Source:
        def __init__(self, host, port, timeout):
            pass

        async def get_info(self):
            return SimpleNamespace(players=3, max_players=10, name="X", game="Valheim")

        async def get_players(self):
            return await names_query()
    _fake_opengsq(monkeypatch, "opengsq.protocols.source", "Source", Source)
    request = GameQueryRequest(container_name="c", host="h", port=2457, protocol="source",
                               timeout_seconds=0.5)
    result = asyncio.run(GameQueryService().get_player_list(request))
    assert result.success is True
    assert (result.players_online, result.max_players, result.server_name) == (3, 10, "X")
    assert result.names == [] and result.names_given is False


@pytest.mark.parametrize("names_query", [_silent, _refused], ids=["silent", "refused"])
def test_palworld_keeps_the_count_and_the_name(monkeypatch, names_query):
    class Palworld:
        def __init__(self, host, port, api_username, api_password, timeout):
            pass

        async def get_status(self):
            return SimpleNamespace(num_players=2, max_players=32, server_name="Pals")

        async def get_players(self):
            return await names_query()
    _fake_opengsq(monkeypatch, "opengsq.protocols.palworld", "Palworld", Palworld)
    request = GameQueryRequest(container_name="c", host="h", port=8212, protocol="palworld",
                               timeout_seconds=0.5)
    result = asyncio.run(GameQueryService().get_player_list(request))
    assert result.success is True
    assert (result.players_online, result.max_players, result.server_name) == (2, 32, "Pals")
    assert result.names == [] and result.names_given is False

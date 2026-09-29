# -*- coding: utf-8 -*-
"""Every container has an info display, and a game server's names who plays (v3.1.0).

OPERATOR, 2026-09-28: every game server has an info display from now on,
not only the ones with a text set - and then the ℹ️ marker in the overviews
can go, since every container has one.

So:

* THE PLAYERS. A game server with the player count switched on names who is
  online, with the time on the server where the game sends it (Source/A2S).
  The names are asked for when the display is opened, never by the status
  cycle, on the port order the status cycle learned, within a budget - the
  dropdown path answers Discord without deferring.
* NOT EVERY GAME NAMES ITS PLAYERS. Icarus sends empty names (opengsq issue
  #44), Satisfactory's API only counts; Minecraft sends a sample of twelve at
  most. The display says so, or "+k more", rather than show a short list.
* EVERY CONTAINER opens the display - status channel button, control channel
  button, the overview dropdown, /info. What was switched off stays hidden:
  a text whose info is off is not shown just because the display opens now.
* NO MARKER: the overviews and the status embeds carry no ⓘ / ℹ️ any more.

COUNTER-CHECK (2026-09-28): with get_player_list trying the ports in reverse,
the port-order case went red; with the empty-name filter removed from the
Source branch, the Icarus case did; with the `shown` gate removed from
_generate_info_embed, the switched-off-text case did; with StatusInfoView
back on `if info enabled`, the every-container case did; with the
support-verdict skip removed from _request_for, the unreachable case did; with
the per-port wait back at the whole budget, the silent-first-port case did.
Later the same day (the operator's text stood last under the dropdown): with
the operator's block moved behind the game and Docker blocks, the ordering
case of each path went red.
"""

import asyncio
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from cogs import info_extras
from services.infrastructure.game_query_service import GameQueryRequest, GameQueryService, PlayerList

ROOT = Path(__file__).resolve().parents[2]


def _fake_opengsq(monkeypatch, module, cls_name, cls):
    mod = ModuleType(module)
    setattr(mod, cls_name, cls)
    monkeypatch.setitem(sys.modules, module, mod)


# --- asking the server ------------------------------------------------------

def test_source_names_the_players_with_their_time(monkeypatch):
    class Source:
        def __init__(self, host, port, timeout):
            pass

        async def get_info(self):
            return SimpleNamespace(players=2, max_players=10)

        async def get_players(self):
            return [SimpleNamespace(name="Anna", duration=4800.0), SimpleNamespace(name="Bob", duration=30.0)]
    _fake_opengsq(monkeypatch, "opengsq.protocols.source", "Source", Source)
    result = asyncio.run(GameQueryService()._query_players("source", "h", 2457, 1.0))
    assert result.names == [("Anna", 4800.0), ("Bob", 30.0)]
    assert (result.players_online, result.max_players, result.names_given) == (2, 10, True)


def test_a_game_that_sends_empty_names_is_said_to(monkeypatch):
    """Icarus: two players counted, two empty names sent."""
    class Source:
        def __init__(self, host, port, timeout):
            pass

        async def get_info(self):
            return SimpleNamespace(players=2, max_players=8)

        async def get_players(self):
            return [SimpleNamespace(name="", duration=10.0), SimpleNamespace(name=" ", duration=20.0)]
    _fake_opengsq(monkeypatch, "opengsq.protocols.source", "Source", Source)
    result = asyncio.run(GameQueryService()._query_players("source", "h", 27015, 1.0))
    assert result.names == [] and result.names_given is False
    assert "does not send player names" in info_extras.format_players(result)


def test_minecraft_sends_a_sample_and_the_rest_is_counted(monkeypatch):
    class Minecraft:
        def __init__(self, host, port, timeout):
            pass

        async def get_status(self):
            return {"players": {"online": 15, "max": 20,
                                "sample": [{"name": f"p{i}", "id": str(i)} for i in range(12)]}}
    _fake_opengsq(monkeypatch, "opengsq.protocols.minecraft", "Minecraft", Minecraft)
    result = asyncio.run(GameQueryService()._query_players("minecraft", "h", 25565, 1.0))
    block = info_extras.format_players(result)
    assert "15/20" in block and "• p11" in block and "+3" in block


def test_satisfactory_counts_and_names_nobody(monkeypatch):
    class Satisfactory:
        def __init__(self, host, port, app_token, timeout):
            pass

        async def get_status(self):
            return SimpleNamespace(state=3, num_players=3, max_players=4, name="Factory")
    _fake_opengsq(monkeypatch, "opengsq.protocols.satisfactory", "Satisfactory", Satisfactory)
    result = asyncio.run(GameQueryService()._query_players("satisfactory", "h", 7777, 1.0, "token"))
    assert (result.players_online, result.names_given, result.server_name) == (3, False, "Factory")


def test_the_ports_are_asked_in_the_learned_order_and_the_winner_is_kept():
    service = GameQueryService()
    service._target_cache[("valheim", "", 0, "source")] = (time.monotonic(), "h", [2456, 2457, 2458])
    asked = []

    async def _players(protocol, host, port, timeout, token=''):
        asked.append(port)
        if port != 2457:
            raise OSError("no answer")
        return PlayerList(success=True, players_online=0, max_players=10)
    service._query_players = _players
    request = GameQueryRequest(container_name="valheim", protocol="source", host="h", port=2456,
                               candidate_ports=(2457, 2458), timeout_seconds=1.0)
    result = asyncio.run(service.get_player_list(request))
    assert result.success and asked == [2456, 2457]
    assert service._target_cache[("valheim", "", 0, "source")][2][0] == 2457


def test_a_server_that_answers_nowhere_is_a_failure_not_an_exception():
    service = GameQueryService()

    async def _players(*args):
        raise RuntimeError("boom")
    service._query_players = _players
    request = GameQueryRequest(container_name="x", protocol="source", host="h", port=1, timeout_seconds=1.0)
    result = asyncio.run(service.get_player_list(request))
    assert (result.success, result.error_type) == (False, "unreachable")


# --- the block ---------------------------------------------------------------

def test_the_block_reads_as_a_list():
    block = info_extras.format_players(PlayerList(
        success=True, players_online=2, max_players=10,
        names=[("An*na", 4800.0), ("Bob", 30.0)]))
    lines = block.split("\n")
    assert "2/10" in lines[0]
    assert lines[1] == "• An\\*na · 1 h 20 min", "a name must not turn into Discord markdown"
    assert lines[2] == "• Bob · under a minute"


def test_nobody_and_unreadable_say_so():
    # "0/10" says nobody plays; a second line repeating it was dropped (operator, 2026-09-28)
    assert info_extras.format_players(PlayerList(success=True, players_online=0, max_players=10)) \
        == "👥 **Players online: 0/10**"
    assert "cannot be read" in info_extras.format_players(PlayerList(success=False))


def test_no_block_without_the_player_count(monkeypatch):
    asked = []
    monkeypatch.setattr(info_extras, "_request_for", lambda cfg: asked.append(cfg))
    assert asyncio.run(info_extras.player_list({"docker_name": "nginx"})) is None
    assert asked == [], "a container without the player count was queried"


def test_the_block_keeps_to_its_budget(monkeypatch):
    async def _slow(cfg):
        await asyncio.sleep(10)
    monkeypatch.setattr(info_extras, "_request_for", _slow)
    monkeypatch.setattr(info_extras, "BUDGET_SECONDS", 0.05)
    started = time.monotonic()
    players = asyncio.run(info_extras.player_list({"docker_name": "valheim", "query_enabled": True}))
    assert time.monotonic() - started < 1.0
    assert "cannot be read" in info_extras.format_players(players)


def test_a_server_found_unreachable_is_not_asked(monkeypatch):
    """Measured live: Enshrouded's support verdict is False and a query to it
    times out. The status cycle skips such a server; the display must too,
    or every opening costs the whole budget for "cannot be read"."""
    import services.infrastructure.game_query_support_service as support_mod
    import services.infrastructure.game_query_service as query_mod
    monkeypatch.setattr(support_mod, "get_game_query_support_service",
                        lambda: SimpleNamespace(is_supported=lambda name: False, get_protocol=lambda name: None))

    class _NoResolve:
        async def resolve_query_candidates(self, *args):
            raise AssertionError("an unreachable server was resolved and asked")
    monkeypatch.setattr(query_mod, "get_game_query_service", lambda: _NoResolve())
    assert asyncio.run(info_extras._request_for({"docker_name": "Enshrouded", "query_enabled": True})) is None


def test_a_silent_first_port_leaves_time_for_the_next(monkeypatch):
    """Measured live: Valheim lists 2456 first and answers on 2457 only. With
    one port allowed the whole budget, the display said "cannot be read"
    until the status cycle had learned the order."""
    import services.infrastructure.game_query_support_service as support_mod
    import services.infrastructure.game_query_service as query_mod
    monkeypatch.setattr(support_mod, "get_game_query_support_service",
                        lambda: SimpleNamespace(is_supported=lambda name: True, get_protocol=lambda name: "source"))

    class _Resolve:
        async def resolve_query_candidates(self, *args):
            return "h", [2456, 2457, 2458]
    monkeypatch.setattr(query_mod, "get_game_query_service", lambda: _Resolve())
    request = asyncio.run(info_extras._request_for({"docker_name": "Valheim", "query_enabled": True}))
    assert request.timeout_seconds * 2 < info_extras.BUDGET_SECONDS, \
        "a silent first port takes the whole budget"


def test_a_stopped_server_gets_no_block(monkeypatch):
    async def _request(cfg):
        return GameQueryRequest(container_name="valheim", protocol="source", host="h", port=1)
    monkeypatch.setattr(info_extras, "_request_for", _request)
    monkeypatch.setattr(info_extras, "_is_running", lambda name: False)
    assert asyncio.run(info_extras.player_list({"docker_name": "valheim", "query_enabled": True})) is None


# --- every container, nothing switched off shown -----------------------------

def _info_service(monkeypatch, info):
    service = SimpleNamespace(get_container_info=lambda name: SimpleNamespace(
        success=True, data=SimpleNamespace(to_dict=lambda: dict(info))))
    monkeypatch.setattr("services.infrastructure.container_info_service.get_container_info_service",
                        lambda: service)
    monkeypatch.setattr("cogs.status_info_integration.get_container_info_service", lambda: service)
    return service


async def test_every_container_gets_the_info_button_and_a_group_none(monkeypatch):
    from cogs.status_info_integration import StatusInfoButton, StatusInfoView
    _info_service(monkeypatch, {"enabled": False})
    view = StatusInfoView(None, {"docker_name": "nginx", "name": "nginx"}, True)
    assert any(isinstance(c, StatusInfoButton) for c in view.children)
    group = StatusInfoView(None, {"docker_name": "group:Games", "name": "Games"}, True)
    assert group.children == []


async def test_a_switched_off_text_stays_hidden_but_the_players_show(monkeypatch):
    from cogs.status_info_integration import StatusInfoButton
    info = {"enabled": False, "custom_text": "Password: secret", "show_ip": True, "custom_ip": "1.2.3.4"}
    _info_service(monkeypatch, info)

    async def _extras(cfg):
        return info_extras.Extras(game=["👥 **Players online: 1/10**", "• Anna"],
                                  docker=["⏱️ Running since …"], port=2456)
    monkeypatch.setattr(info_extras, "info_extras", _extras)
    button = StatusInfoButton(None, {"docker_name": "valheim", "name": "Valheim"}, info)
    text = (await button._generate_info_embed(include_protected=False)).description
    assert "secret" not in text and "1.2.3.4" not in text
    assert "• Anna" in text

    info["enabled"] = True
    text = (await button._generate_info_embed(include_protected=False)).description
    assert "Password: secret" in text, "the switch now hides a text that is on"
    # The operator's words first, then the game, then Docker - apart by blank lines
    # (operator, 2026-09-28: his text stood last on the dropdown path)
    own, game, docker = text.split("\n\n")
    assert own == "🔗 **Custom Address:** `1.2.3.4:2456`\nPassword: secret", own
    assert game.startswith("👥") and docker.startswith("⏱️")


async def test_the_dropdown_puts_the_operators_words_first_too(monkeypatch):
    """The overview dropdown built its own embed with the text as a field below
    everything. Through the real selection callback."""
    from cogs import control_ui
    from types import SimpleNamespace

    async def _extras(cfg):
        return info_extras.Extras(game=["🎯 **BachelorLaming**"], docker=["⏱️ Running since …"])
    monkeypatch.setattr(info_extras, "info_extras", _extras)
    server = {"docker_name": "Valheim", "container_name": "Valheim", "display_name": ["Valheim"],
              "info": {"enabled": True, "custom_text": "Worldname: DrKongo"}}
    monkeypatch.setattr(control_ui, "get_server_config_service",
                        lambda: SimpleNamespace(get_server_by_docker_name=lambda name: server,
                                                get_all_servers=lambda: [server]))
    shown = {}

    async def _edit(**kwargs):
        shown.update(kwargs)
    async def _defer(**_kwargs):
        return None
    # Deferred first, then the original response is edited (final check before v3.1.0)
    interaction = SimpleNamespace(channel=None, user=SimpleNamespace(id=1, name="op"),
                                  response=SimpleNamespace(edit_message=_edit, defer=_defer,
                                                           is_done=lambda: False),
                                  edit_original_response=_edit)
    dropdown = control_ui.ContainerInfoDropdown(
        None, [{"name": "Valheim", "display": "Valheim", "protected": False, "order": 1}])
    dropdown._interaction, dropdown._selected_values = interaction, ["Valheim"]  # as py-cord sets them
    await dropdown.callback(interaction)
    embed = shown["embed"]
    assert embed.description.split("\n\n") == ["Worldname: DrKongo", "🎯 **BachelorLaming**", "⏱️ Running since …"]
    assert not embed.fields, "the operator's text is still a field below everything"


def test_no_path_refuses_a_container_without_info_text():
    for path, sentence in (("cogs/control_ui.py", "Container information is not enabled for"),
                           ("cogs/control_ui.py", "Container info is not configured for this container"),
                           ("cogs/slash_commands.py", "Container information is not enabled for")):
        assert sentence not in (ROOT / path).read_text(encoding="utf-8"), (path, sentence)
    source = (ROOT / "cogs" / "control_ui.py").read_text(encoding="utf-8")
    assert "if info_config.get('enabled', False) or info_config.get('protected_enabled', False):" not in source, \
        "the overview dropdown still lists only containers with a text"


def test_the_overviews_carry_no_info_marker():
    source = (ROOT / "cogs" / "overview_embeds.py").read_text(encoding="utf-8")
    assert "get_container_info" not in source, "the overview still asks who has info"
    assert 'container_line += " ⓘ"' not in source and '" ℹ️"' not in source
    assert "Additional info available" not in (ROOT / "cogs" / "status_info_integration.py").read_text(encoding="utf-8")

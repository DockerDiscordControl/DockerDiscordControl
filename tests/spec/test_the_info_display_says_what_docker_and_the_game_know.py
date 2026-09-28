# -*- coding: utf-8 -*-
"""The info display says what Docker and the game server know (v3.0.2).

OPERATOR, 2026-09-28: general container information - uptime, version where
possible, and whatever else is worth knowing. Agreed:

* THE GAME SERVER: the name players look for in the server browser, game and
  version, a password, the port to connect to. Measured answers of the
  operator's servers (2026-09-28) are the fixtures below: A2S's version field
  holds a placeholder ("1.0.0.0" from Valheim, "0.0.0.1" from Icarus), the
  real version is in the keywords.
* DOCKER, FOR EVERY CONTAINER - DDC is not only for game servers (operator,
  same day): running since / stopped since and why for everyone; version,
  image date, restart policy and memory limit only where the container's
  details are allowed - the switch that already hides CPU and RAM.
* UNRAID'S CONTAINERS carry the restart policy "no" and are started at boot by
  Unraid's own autostart, which Docker cannot see. "No automatic restart" was
  wrong for all of them (seen live on plex, AdGuard, duckdns); what is true is
  that Docker does not bring them back after a crash.
* A VERSION IS NOT GUESSED: an image built FROM ubuntu inherits "22.04" as its
  version label (carmeet-api, measured) and "master" is no version. Then the
  tag, then only the image date.
* A PORT IS NOT GUESSED: the server names its port inside the container. The
  published host port counts; the same port only on the host network or an
  Unraid LAN network (br0); on an unpublished bridge there is none to show.

COUNTER-CHECK (2026-09-28): with the ref.name check removed from version_of,
the inherited-version case went red; with format_facts ignoring `details`, the
details case did; with info_extras awaiting the Docker facts only after the
game query, the side-by-side case did; with connect_port returning the game
port for every network, the port case did.
"""

import asyncio
import sys
import time
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace

from cogs import info_extras
from services.infrastructure import container_facts_service as facts_mod
from services.infrastructure.container_facts_service import (ContainerFacts, connect_port,
                                                             facts_from_attrs, version_of)
from services.infrastructure.game_query_service import GameQueryService, PlayerList, a2s_version

# The Valheim answer, as opengsq returned it on 2026-09-28 (players added)
VALHEIM_INFO = SimpleNamespace(
    protocol=17, name='BachelorLaming', map='BachelorLaming', folder='valheim', game='', bots=0,
    visibility=SimpleNamespace(value=1), version='1.0.0.0', port=2456,
    keywords='g=1.0.16,n=40,m=', players=1, max_players=10)


# --- the game server ---------------------------------------------------------

def test_the_real_version_is_read_from_the_keywords():
    assert a2s_version('1.0.0.0', 'g=1.0.16,n=40,m=') == '1.0.16'
    assert a2s_version('0.0.0.1', 'BUILDID:0,OWNINGNAME:LuigisIcarus,P_s:Lobby,G_s:3.0.29.157838-x-x') \
        == '3.0.29.157838'
    assert a2s_version('0.0.0.1', 'BUILDID:0') is None, "a placeholder was shown as a version"
    assert a2s_version('1.40.1.5', '') == '1.40.1.5'


def test_a_source_server_says_its_name_game_version_password_and_port(monkeypatch):
    class Source:
        def __init__(self, host, port, timeout):
            pass

        async def get_info(self):
            return VALHEIM_INFO

        async def get_players(self):
            return [SimpleNamespace(name='Anna', duration=60.0)]
    module = ModuleType('opengsq.protocols.source')
    module.Source = Source
    monkeypatch.setitem(sys.modules, 'opengsq.protocols.source', module)
    result = asyncio.run(GameQueryService()._query_players('source', 'h', 2457, 1.0))
    assert (result.server_name, result.game, result.game_version, result.password, result.game_port) \
        == ('BachelorLaming', 'Valheim', '1.0.16', True, 2456)


def test_the_game_line_reads_as_one_line():
    players = PlayerList(success=True, players_online=1, max_players=10, server_name='Bachelor*Laming',
                         game='Valheim', game_version='1.0.16', password=True, game_port=2456)
    facts = ContainerFacts(published={(2456, 'udp'): 12456})
    assert info_extras.game_line(players, facts) == \
        '🎯 **Bachelor\\*Laming** · Valheim 1.0.16 · 🔒 Password · Port 12456'
    assert info_extras.game_line(PlayerList(success=False), facts) is None


def test_a_port_is_shown_only_where_a_player_can_reach_it():
    assert connect_port(ContainerFacts(published={(2456, 'udp'): 12456}), 2456) == 12456
    assert connect_port(ContainerFacts(network_mode='host'), 2456) == 2456
    assert connect_port(ContainerFacts(network_mode='br0'), 2456) == 2456
    assert connect_port(ContainerFacts(network_mode='verwaltli-network'), 2456) is None
    assert connect_port(ContainerFacts(network_mode='bridge', published={(80, 'tcp'): 8080}), 2456) is None
    assert connect_port(None, 2456) is None


# --- Docker ------------------------------------------------------------------

def test_the_version_comes_from_the_labels_then_the_tag():
    lsio = {'org.opencontainers.image.version': '1.43.4.10903-e5521bd8c-ls325',
            'org.opencontainers.image.ref.name': 'b5c3c39e8bd5e37234f52564ce0be543e20e71f6'}
    assert version_of(lsio, 'lscr.io/linuxserver/plex') == '1.43.4.10903-e5521bd8c-ls325'
    assert version_of({'org.label-schema.version': '26.09.1'}, 'jlesage/nginx-proxy-manager') == '26.09.1'
    assert version_of({'version': 'RELEASE.2025-09-07T16-13-09Z'}, 'minio/minio') == 'RELEASE.2025-09-07T16-13-09Z'
    assert version_of({}, 'redis:7-alpine') == '7-alpine'
    assert version_of({}, 'lscr.io/linuxserver/plex:latest') is None
    assert version_of({}, 'registry.local:5000/app') is None, "a registry port was read as a tag"
    assert version_of({'org.opencontainers.image.version': 'master'}, 'ghcr.io/librespeed/speedtest') is None


def test_an_inherited_base_system_version_is_not_the_apps():
    """carmeet-api, measured: built FROM ubuntu, labelled only by ubuntu."""
    labels = {'org.opencontainers.image.ref.name': 'ubuntu', 'org.opencontainers.image.version': '22.04'}
    assert version_of(labels, 'carmeet-api') is None


def test_docker_state_is_read_as_docker_writes_it():
    running = facts_from_attrs({
        'State': {'Running': True, 'StartedAt': '2026-09-28T06:57:39.472938994Z',
                  'FinishedAt': '0001-01-01T00:00:00Z', 'ExitCode': 0},
        'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped'}, 'Memory': 0, 'NetworkMode': 'bridge'},
        'Config': {'Image': 'ich777/steamcmd:valheim', 'Labels': {}},
        'NetworkSettings': {'Ports': {'2456/udp': [{'HostIp': '0.0.0.0', 'HostPort': '2456'}],
                                      '9000/tcp': None}}},
        {'Created': '2026-09-25T08:02:35.754545324+02:00'})
    assert running.started_at == datetime(2026, 9, 28, 6, 57, 39, 472938, tzinfo=timezone.utc)
    assert running.finished_at is None and running.exit_code is None
    assert running.image_created.year == 2026 and running.version is None, "a tag without a digit is no version"
    assert running.published == {(2456, 'udp'): 2456}

    stopped = facts_from_attrs({'State': {'Running': False, 'FinishedAt': '2026-09-02T11:06:36Z',
                                          'ExitCode': 137, 'OOMKilled': True}})
    assert stopped.started_at is None and stopped.exit_code == 137 and stopped.oom_killed


def test_a_stop_says_why_only_when_it_was_not_ordinary():
    when = datetime(2026, 9, 2, tzinfo=timezone.utc)
    line = lambda **kw: info_extras.format_facts(ContainerFacts(finished_at=when, **kw), details=False)[0]
    assert '·' not in line(exit_code=143), "an ordinary docker stop was shown as a reason"
    assert 'exit code 1' in line(exit_code=1)
    assert 'out of memory' in line(exit_code=137, oom_killed=True)
    assert f'<t:{int(when.timestamp())}:f>' in line(exit_code=0), "not a Discord timestamp"


def test_the_technical_lines_need_the_details_switch():
    facts = ContainerFacts(running=True, started_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
                           version='1.43.4', image_created=datetime(2026, 9, 21, tzinfo=timezone.utc),
                           restart_policy='unless-stopped', memory_limit=4 * 1024 ** 3)
    public = info_extras.format_facts(facts, details=False)
    assert len(public) == 1 and public[0].startswith('⏱️')
    full = '\n'.join(info_extras.format_facts(facts, details=True))
    assert '📦 1.43.4 · image from <t:' in full
    assert 'after a crash or a reboot' in full and 'Memory limit: 4.0 GB' in full


# --- together ----------------------------------------------------------------

def test_game_query_and_docker_run_side_by_side(monkeypatch):
    async def _facts(name):
        await asyncio.sleep(0.4)
        return ContainerFacts(running=True, started_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
                              version='1.0', restart_policy='no')

    async def _players(cfg):
        await asyncio.sleep(0.4)
        return PlayerList(success=True, players_online=0, max_players=10, server_name='BachelorLaming')
    monkeypatch.setattr(facts_mod, 'get_container_facts', _facts)
    monkeypatch.setattr(info_extras, 'player_list', _players)
    started = time.monotonic()
    lines = asyncio.run(info_extras.info_extras({'docker_name': 'Valheim', 'allow_detailed_status': False}))
    assert time.monotonic() - started < 0.7, "the two lookups ran one after the other"
    assert lines[0].startswith('🎯 **BachelorLaming**') and 'Nobody is playing' in lines[1]
    assert not any(line.startswith('📦') for line in lines), "details shown where they are switched off"


def test_an_unraid_container_is_not_said_to_stay_down_after_a_reboot():
    facts = ContainerFacts(running=True, started_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
                           restart_policy='no')
    text = '\n'.join(info_extras.format_facts(facts, details=True))
    assert 'Docker does not restart it after a crash' in text
    assert 'No automatic restart' not in text


def test_a_plain_container_gets_the_docker_facts_and_nothing_about_games(monkeypatch):
    """AdGuard, as measured: no game server, details allowed."""
    async def _facts(name):
        return ContainerFacts(running=True, started_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
                              version='v0.107.79', image_created=datetime(2026, 8, 18, tzinfo=timezone.utc),
                              restart_policy='no', network_mode='br0')
    monkeypatch.setattr(facts_mod, 'get_container_facts', _facts)
    lines = asyncio.run(info_extras.info_extras({'docker_name': 'AdGuard-Home'}))
    assert [line.split(' ')[0] for line in lines] == ['⏱️', '📦', '🔁'], lines
    assert 'v0.107.79' in lines[1]

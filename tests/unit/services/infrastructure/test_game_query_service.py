#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for GameQueryService (game-server player-count queries via opengsq).

opengsq is NOT installed in the test env on purpose - the service imports it
lazily, so these tests either patch the protocol method or inject a fake opengsq
module into sys.modules. The Docker client is mocked for port autodiscovery.
"""
import asyncio
import sys
import types

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.infrastructure.game_query_service import (
    GameQueryService, GameQueryRequest, GameQueryResult,
    get_game_query_service, reset_game_query_service, SUPPORTED_PROTOCOLS,
)


def _req(name="valheim", protocol="source", host="10.0.0.5", port=2457, timeout=5.0, token=""):
    return GameQueryRequest(container_name=name, protocol=protocol, host=host,
                            port=port, timeout_seconds=timeout, token=token)


def _inject_opengsq_protocol(protocol_name, class_name, cls):
    """Build a patch.dict mapping that injects a fake opengsq.protocols.<name> module."""
    import types as _types
    fake = _types.ModuleType(f'opengsq.protocols.{protocol_name}')
    setattr(fake, class_name, cls)
    return {
        'opengsq': _types.ModuleType('opengsq'),
        'opengsq.protocols': _types.ModuleType('opengsq.protocols'),
        f'opengsq.protocols.{protocol_name}': fake,
    }


# ---------------------------------------------------------------------------
# get_game_query: success / cache / graceful failure
# ---------------------------------------------------------------------------

class TestGetGameQuery:
    async def test_success_returns_player_counts(self):
        svc = GameQueryService()
        svc._query_protocol = AsyncMock(return_value=(3, 10))
        r = await svc.get_game_query(_req())
        assert r.success and r.players_online == 3 and r.max_players == 10
        assert r.cached is False and r.error_type is None

    async def test_second_call_is_cache_hit(self):
        svc = GameQueryService()
        svc._query_protocol = AsyncMock(return_value=(5, 20))
        first = await svc.get_game_query(_req())
        second = await svc.get_game_query(_req())
        assert first.cached is False and second.cached is True
        assert second.players_online == 5
        svc._query_protocol.assert_awaited_once()  # only one real query

    async def test_expired_cache_requeries(self):
        svc = GameQueryService(cache_ttl_seconds=0.0)  # everything is instantly stale
        svc._query_protocol = AsyncMock(return_value=(1, 4))
        await svc.get_game_query(_req())
        await svc.get_game_query(_req())
        assert svc._query_protocol.await_count == 2

    async def test_timeout_is_graceful(self):
        svc = GameQueryService()

        async def _hang(*a, **k):
            await asyncio.sleep(10)

        svc._query_protocol = _hang
        r = await svc.get_game_query(_req(timeout=0.05))
        assert r.success is False and r.error_type == 'timeout'
        assert r.players_online is None  # never raises

    async def test_dead_server_is_graceful(self):
        svc = GameQueryService()
        svc._query_protocol = AsyncMock(side_effect=ConnectionRefusedError("refused"))
        r = await svc.get_game_query(_req())
        assert r.success is False and r.error_type == 'unreachable'

    async def test_unsupported_protocol_is_bad_config(self):
        svc = GameQueryService()
        r = await svc.get_game_query(_req(protocol="quake3"))
        assert r.success is False and r.error_type == 'bad_config'

    async def test_fetch_falls_back_to_candidate_port(self):
        # primary (game) port times out; the A2S query port in candidate_ports answers
        svc = GameQueryService()

        async def _proto(protocol, host, port, timeout, token=''):
            if port == 17777:
                raise ConnectionError("game port - no A2S here")
            return (2, 8)

        svc._query_protocol = _proto
        r = await svc.get_game_query(GameQueryRequest(
            container_name="icarus", protocol="source", host="h", port=17777, candidate_ports=(27015,)))
        assert r.success and (r.players_online, r.max_players) == (2, 8)

    async def test_fetch_uses_primary_when_it_answers(self):
        svc = GameQueryService()
        tried = []

        async def _proto(protocol, host, port, timeout, token=''):
            tried.append(port)
            return (1, 4)

        svc._query_protocol = _proto
        r = await svc.get_game_query(GameQueryRequest(
            container_name="x", protocol="source", host="h", port=27015, candidate_ports=(17777,)))
        assert r.success and tried == [27015]  # fallback never tried

    async def test_missing_host_or_port_is_no_query(self):
        svc = GameQueryService()
        assert (await svc.get_game_query(_req(host=""))).error_type == 'no_query'
        assert (await svc.get_game_query(_req(port=0))).error_type == 'no_query'


# ---------------------------------------------------------------------------
# bulk: one dead server must not kill the others
# ---------------------------------------------------------------------------

class TestDetectSupport:
    async def test_source_answer_means_supported(self):
        svc = GameQueryService()
        svc.resolve_query_candidates = AsyncMock(return_value=("h", [27015, 17777]))
        svc._fetch = AsyncMock(return_value=GameQueryResult(
            success=True, container_name="x", players_online=0, max_players=8))
        ok, proto, port = await svc.detect_support("x")
        assert ok is True and proto == "source"

    async def test_no_answer_on_any_protocol_means_unsupported(self):
        svc = GameQueryService()
        svc.resolve_query_candidates = AsyncMock(return_value=("h", [1234]))
        svc._fetch = AsyncMock(return_value=GameQueryResult(
            success=False, container_name="x", error_type="timeout"))
        ok, proto, port = await svc.detect_support("x")
        assert ok is False and proto is None and port is None

    async def test_falls_through_to_minecraft(self):
        svc = GameQueryService()
        svc.resolve_query_candidates = AsyncMock(return_value=("h", [25565]))

        async def _fetch(req):
            return GameQueryResult(success=(req.protocol == "minecraft"),
                                   container_name="x", players_online=2, max_players=20)

        svc._fetch = _fetch
        ok, proto, port = await svc.detect_support("x")
        assert ok is True and proto == "minecraft"


class TestBulk:
    async def test_empty_returns_empty(self):
        assert await GameQueryService().get_bulk_game_queries([]) == {}

    async def test_one_dead_does_not_kill_others(self):
        svc = GameQueryService()

        async def _proto(protocol, host, port, timeout, token=''):
            if host == "dead":
                raise ConnectionError("boom")
            return (2, 8)

        svc._query_protocol = _proto
        reqs = [_req("a", host="alive1"), _req("b", host="dead"), _req("c", host="alive2")]
        out = await svc.get_bulk_game_queries(reqs)
        assert set(out) == {"a", "b", "c"}
        assert out["a"].success and out["a"].players_online == 2
        assert out["c"].success
        assert out["b"].success is False and out["b"].error_type == 'unreachable'

    async def test_result_per_request_even_on_internal_error(self):
        svc = GameQueryService()
        # get_game_query itself blows up -> gather(return_exceptions=True) catches it
        svc.get_game_query = AsyncMock(side_effect=RuntimeError("kaboom"))
        out = await svc.get_bulk_game_queries([_req("x")])
        assert out["x"].success is False and out["x"].error_type == 'unreachable'


# ---------------------------------------------------------------------------
# protocol dispatch (lazy opengsq import) via injected fake module
# ---------------------------------------------------------------------------

class TestProtocolDispatch:
    async def test_source_extracts_players_and_max(self):
        created = {}

        class _FakeInfo:
            players = 4
            max_players = 16

        class _FakeSource:
            def __init__(self, host, port, timeout):
                created['args'] = (host, port, timeout)

            async def get_info(self):
                return _FakeInfo()

        fake_src = types.ModuleType('opengsq.protocols.source')
        fake_src.Source = _FakeSource
        mods = {
            'opengsq': types.ModuleType('opengsq'),
            'opengsq.protocols': types.ModuleType('opengsq.protocols'),
            'opengsq.protocols.source': fake_src,
        }
        with patch.dict(sys.modules, mods):
            players, mx = await GameQueryService()._query_protocol('source', '1.2.3.4', 2457, 5.0)
        assert (players, mx) == (4, 16)
        assert created['args'] == ('1.2.3.4', 2457, 5.0)

    async def test_unsupported_protocol_raises_in_dispatch(self):
        with pytest.raises(ValueError):
            await GameQueryService()._query_protocol('nope', 'h', 1, 1.0)

    async def test_minecraft_extracts_online_and_max(self):
        class _FakeMC:
            def __init__(self, host, port, timeout):
                pass

            async def get_status(self):
                return {'players': {'online': 7, 'max': 20}, 'version': {'name': '1.20'}}

        mods = _inject_opengsq_protocol('minecraft', 'Minecraft', _FakeMC)
        with patch.dict(sys.modules, mods):
            players, mx = await GameQueryService()._query_protocol('minecraft', '1.2.3.4', 25565, 5.0)
        assert (players, mx) == (7, 20)

    async def test_satisfactory_uses_token_and_extracts_counts(self):
        created = {}

        class _FakeStatus:
            num_players = 3
            max_players = 4

        class _FakeSat:
            def __init__(self, host, port, app_token, timeout):
                created['token'] = app_token

            async def get_status(self):
                return _FakeStatus()

        mods = _inject_opengsq_protocol('satisfactory', 'Satisfactory', _FakeSat)
        with patch.dict(sys.modules, mods):
            players, mx = await GameQueryService()._query_protocol('satisfactory', '1.2.3.4', 7777, 5.0, token='APITOKEN')
        assert (players, mx) == (3, 4)
        assert created['token'] == 'APITOKEN'

    async def test_satisfactory_no_save_loaded_reports_no_count(self):
        # state != 3 -> opengsq returns 0/0; we surface "no count" rather than 0/0
        class _FakeStatus:
            num_players = 0
            max_players = 0

        class _FakeSat:
            def __init__(self, host, port, app_token, timeout):
                pass

            async def get_status(self):
                return _FakeStatus()

        mods = _inject_opengsq_protocol('satisfactory', 'Satisfactory', _FakeSat)
        with patch.dict(sys.modules, mods):
            players, mx = await GameQueryService()._query_protocol('satisfactory', 'h', 7777, 5.0)
        assert (players, mx) == (None, None)

    async def test_satisfactory_zero_players_with_save_shows_real_zero(self):
        # save loaded (max>0) but empty server -> a real 0, NOT "no count"
        class _FakeStatus:
            num_players = 0
            max_players = 4

        class _FakeSat:
            def __init__(self, host, port, app_token, timeout):
                pass

            async def get_status(self):
                return _FakeStatus()

        mods = _inject_opengsq_protocol('satisfactory', 'Satisfactory', _FakeSat)
        with patch.dict(sys.modules, mods):
            players, mx = await GameQueryService()._query_protocol('satisfactory', 'h', 7777, 5.0)
        assert (players, mx) == (0, 4)

    async def test_palworld_uses_admin_password_and_extracts_counts(self):
        created = {}

        class _FakeStatus:
            num_players = 5
            max_players = 32

        class _FakePal:
            def __init__(self, host, port, api_username, api_password, timeout):
                created['user'] = api_username
                created['pw'] = api_password

            async def get_status(self):
                return _FakeStatus()

        mods = _inject_opengsq_protocol('palworld', 'Palworld', _FakePal)
        with patch.dict(sys.modules, mods):
            players, mx = await GameQueryService()._query_protocol('palworld', 'h', 8212, 5.0, token='secretpw')
        assert (players, mx) == (5, 32)
        assert created['user'] == 'admin' and created['pw'] == 'secretpw'

    async def test_source_with_missing_max_returns_none_max(self):
        class _FakeInfo:
            players = 4
            max_players = None

        class _FakeSource:
            def __init__(self, host, port, timeout):
                pass

            async def get_info(self):
                return _FakeInfo()

        mods = _inject_opengsq_protocol('source', 'Source', _FakeSource)
        with patch.dict(sys.modules, mods):
            players, mx = await GameQueryService()._query_protocol('source', 'h', 2457, 5.0)
        assert (players, mx) == (4, None)


# ---------------------------------------------------------------------------
# port autodiscovery
# ---------------------------------------------------------------------------

class TestPortResolution:
    def test_first_published_port_prefers_udp(self):
        ports = {
            "27015/tcp": [{"HostIp": "0.0.0.0", "HostPort": "27015"}],
            "2457/udp": [{"HostIp": "0.0.0.0", "HostPort": "2457"}],
        }
        assert GameQueryService._first_published_port(ports) == 2457

    def test_first_published_port_falls_back_to_tcp(self):
        ports = {"27015/tcp": [{"HostIp": "0.0.0.0", "HostPort": "27015"}]}
        assert GameQueryService._first_published_port(ports) == 27015

    def test_first_published_port_minecraft_prefers_tcp(self):
        # minecraft is a TCP query: must not pick an unrelated UDP side-port
        ports = {
            "25565/tcp": [{"HostIp": "0.0.0.0", "HostPort": "25565"}],
            "24454/udp": [{"HostIp": "0.0.0.0", "HostPort": "24454"}],  # Simple Voice Chat
        }
        assert GameQueryService._first_published_port(ports, 'minecraft') == 25565
        # default (source/satisfactory) still prefers UDP
        assert GameQueryService._first_published_port(ports, 'source') == 24454

    def test_candidate_ports_floats_steam_query_range_first(self):
        # Icarus publishes game port 17777 + A2S query port 27015; only 27015 answers A2S.
        ports = {
            "17777/udp": [{"HostPort": "17777"}],
            "27015/udp": [{"HostPort": "27015"}],
        }
        assert GameQueryService._candidate_ports(ports, 'source') == [27015, 17777]
        assert GameQueryService._first_published_port(ports, 'source') == 27015

    def test_candidate_ports_keeps_game_port_as_fallback(self):
        ports = {"17778/udp": [{"HostPort": "17778"}], "27020/udp": [{"HostPort": "27020"}]}
        cands = GameQueryService._candidate_ports(ports, 'source')
        assert cands[0] == 27020 and 17778 in cands

    def test_candidate_ports_palworld_prefers_tcp(self):
        # Palworld's REST API is HTTP/TCP (default 8212), not the UDP game port
        ports = {"8211/udp": [{"HostPort": "8211"}], "8212/tcp": [{"HostPort": "8212"}]}
        assert GameQueryService._candidate_ports(ports, 'palworld')[0] == 8212

    def test_first_published_port_none_when_unpublished(self):
        assert GameQueryService._first_published_port({"2457/udp": None}) is None
        assert GameQueryService._first_published_port({}) is None

    async def test_configured_port_overrides_autodiscovery(self):
        svc = GameQueryService()
        # Docker must NOT be touched when a port is configured.
        with patch('services.docker_service.docker_client_pool.get_docker_client_async') as gc:
            port = await svc.resolve_query_port("valheim", configured_port=9999)
            assert port == 9999
            gc.assert_not_called()

    async def test_autodiscovers_port_from_docker(self):
        svc = GameQueryService()
        fake_container = MagicMock()
        fake_container.attrs = {"NetworkSettings": {"Ports": {
            "2457/udp": [{"HostIp": "0.0.0.0", "HostPort": "2457"}]}}}
        fake_client = MagicMock()
        fake_client.containers.get.return_value = fake_container

        class _CM:
            async def __aenter__(self):
                return fake_client

            async def __aexit__(self, *a):
                return False

        with patch('services.docker_service.docker_client_pool.get_docker_client_async',
                   return_value=_CM()):
            port = await svc.resolve_query_port("valheim", configured_port=0)
        assert port == 2457

    async def test_autodiscovery_failure_returns_none(self):
        svc = GameQueryService()
        with patch('services.docker_service.docker_client_pool.get_docker_client_async',
                   side_effect=RuntimeError("docker down")):
            assert await svc.resolve_query_port("valheim", configured_port=0) is None


# ---------------------------------------------------------------------------
# singleton + result helpers
# ---------------------------------------------------------------------------

class TestSingletonAndHelpers:
    def test_singleton_is_stable_and_resettable(self):
        reset_game_query_service()
        a = get_game_query_service()
        assert get_game_query_service() is a
        reset_game_query_service()
        assert get_game_query_service() is not a

    def test_result_factories(self):
        assert GameQueryResult.disabled("c").error_type == 'disabled'
        assert GameQueryResult.no_query("c").error_type == 'no_query'

    def test_source_is_supported(self):
        assert 'source' in SUPPORTED_PROTOCOLS

    def test_minecraft_and_satisfactory_supported(self):
        assert 'minecraft' in SUPPORTED_PROTOCOLS
        assert 'satisfactory' in SUPPORTED_PROTOCOLS
        assert 'palworld' in SUPPORTED_PROTOCOLS


# ---------------------------------------------------------------------------
# resolve_query_target (host + port) + container IP
# ---------------------------------------------------------------------------

class TestResolveTarget:
    def test_container_ip_prefers_default_bridge(self):
        net = {"IPAddress": "172.17.0.5", "Networks": {"custom": {"IPAddress": "10.1.1.9"}}}
        assert GameQueryService._container_ip(net) == "172.17.0.5"

    def test_container_ip_falls_back_to_named_network(self):
        net = {"IPAddress": "", "Networks": {"br0": {"IPAddress": "10.1.1.9"}}}
        assert GameQueryService._container_ip(net) == "10.1.1.9"

    def test_container_ip_none_for_host_network(self):
        assert GameQueryService._container_ip({"IPAddress": "", "Networks": {}}) is None

    async def test_configured_host_and_port_skip_docker(self):
        svc = GameQueryService()
        with patch('services.docker_service.docker_client_pool.get_docker_client_async') as gc:
            host, port = await svc.resolve_query_target("v", "1.2.3.4", 2457)
            assert (host, port) == ("1.2.3.4", 2457)
            gc.assert_not_called()

    async def test_autodiscovers_host_and_port(self):
        svc = GameQueryService()
        c = MagicMock()
        c.attrs = {"NetworkSettings": {"IPAddress": "172.17.0.5",
                                       "Ports": {"2457/udp": [{"HostPort": "2457"}]}}}
        client = MagicMock()
        client.containers.get.return_value = c

        class _CM:
            async def __aenter__(self): return client
            async def __aexit__(self, *a): return False

        with patch('services.docker_service.docker_client_pool.get_docker_client_async', return_value=_CM()):
            host, port = await svc.resolve_query_target("v", "", 0)
        assert (host, port) == ("172.17.0.5", 2457)

    async def test_returns_none_when_undiscoverable(self):
        svc = GameQueryService()
        with patch('services.docker_service.docker_client_pool.get_docker_client_async',
                   side_effect=RuntimeError("no docker")):
            assert await svc.resolve_query_target("v", "", 0) == (None, None)


# ---------------------------------------------------------------------------
# ContainerStatusResult player fields (backward compatible)
# ---------------------------------------------------------------------------

class TestContainerStatusPlayers:
    def test_success_result_without_players_defaults_none(self):
        from services.docker_status.models import ContainerStatusResult
        r = ContainerStatusResult.success_result("v", "V", True, "1%", "1MB", "1m", True)
        assert r.players_online is None and r.max_players is None

    def test_success_result_with_players(self):
        from services.docker_status.models import ContainerStatusResult
        r = ContainerStatusResult.success_result("v", "V", True, "1%", "1MB", "1m", True,
                                                 players_online=3, max_players=10)
        assert r.players_online == 3 and r.max_players == 10

    def test_as_tuple_shape_unchanged(self):
        from services.docker_status.models import ContainerStatusResult
        r = ContainerStatusResult.success_result("v", "V", True, "1%", "1MB", "1m", True, 3, 10)
        assert len(r.as_tuple()) == 6  # legacy 6-tuple, players not leaked

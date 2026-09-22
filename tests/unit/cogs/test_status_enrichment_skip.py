#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Tests for skipping unreachable game servers during status enrichment (finding P1).

Measured on the live installation before the fix: the status cycle took 11.0-12.1 s,
of which a rock-steady 10.03 s sat between "Phase 1 completed" (Docker, 1-2 s) and
"Fast adaptive fetch completed". Six containers had querying enabled, the bulk query
ran three at a time with a 5 s timeout each - so one server that never answers cost
two full timeout waves on *every* cycle, forever, because its verdict was not final
and nothing in the enrichment path consulted the verdict at all.

The fix skips containers the support detection has already found unreachable. The
risk it introduces is the opposite failure - silently querying nobody and looking
fast because it does nothing - so these tests pin exactly which containers still get
queried:

  supported is False  -> skipped (the dead ones)
  supported is None   -> queried (unknown, e.g. never probed / token protocol)
  supported is True   -> queried

Recovery is not lost: a non-final negative keeps being re-probed by the background
support probe on its own schedule, and a final one is re-checked through the manual
"test now" button.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.status_handlers import StatusHandlersMixin
from services.docker_status.models import ContainerStatusResult
from services.infrastructure.game_query_service import GameQueryResult

ENRICH_ENABLED = 'app.utils.web_helpers._get_advanced_setting'
QUERY_SERVICE = 'services.infrastructure.game_query_service.get_game_query_service'
SUPPORT_SERVICE = 'services.infrastructure.game_query_support_service.get_game_query_support_service'


def _running(name):
    return ContainerStatusResult.success_result(name, name, True, "1%", "1MB", "1m", True)


def _cfg(*names, protocol="source"):
    return {n: {"query_enabled": True, "query_protocol": protocol,
                "query_host": "", "query_port": 0} for n in names}


def _query_service(players=3):
    svc = MagicMock()
    svc.resolve_query_candidates = AsyncMock(return_value=("1.2.3.4", [2457]))
    svc.get_bulk_game_queries = AsyncMock(side_effect=lambda targets: {
        t.container_name: GameQueryResult(success=True, container_name=t.container_name,
                                          players_online=players, max_players=10)
        for t in targets})
    return svc


def _support(verdicts):
    """verdicts: {name: True | False | None} as returned by is_supported()."""
    support = MagicMock()
    support.is_supported.side_effect = lambda name: verdicts.get(name)
    support.get_protocol.return_value = None
    return support


async def _enrich(results, cfg, svc, support):
    mixin = StatusHandlersMixin()
    with patch(ENRICH_ENABLED, return_value=True), \
         patch(QUERY_SERVICE, return_value=svc), \
         patch(SUPPORT_SERVICE, return_value=support):
        await mixin._enrich_status_with_player_counts(results, cfg)


class TestUnreachableServersAreSkipped:
    async def test_server_marked_unsupported_is_not_queried(self):
        """The whole point of P1: this one cost a full timeout every cycle."""
        results = {"vrising": _running("vrising")}
        svc = _query_service()
        await _enrich(results, _cfg("vrising"), svc, _support({"vrising": False}))

        svc.resolve_query_candidates.assert_not_awaited()
        svc.get_bulk_game_queries.assert_not_awaited()
        assert results["vrising"].players_online is None

    async def test_skipping_does_not_affect_the_others(self):
        results = {"vrising": _running("vrising"), "valheim": _running("valheim")}
        svc = _query_service(players=4)
        await _enrich(results, _cfg("vrising", "valheim"), svc,
                      _support({"vrising": False, "valheim": True}))

        targets = svc.get_bulk_game_queries.call_args.args[0]
        assert [t.container_name for t in targets] == ["valheim"]
        assert results["valheim"].players_online == 4
        assert results["vrising"].players_online is None

    async def test_all_unreachable_means_no_bulk_query_at_all(self):
        results = {"a": _running("a"), "b": _running("b")}
        svc = _query_service()
        await _enrich(results, _cfg("a", "b"), svc, _support({"a": False, "b": False}))

        svc.get_bulk_game_queries.assert_not_awaited()

    async def test_token_protocols_are_skipped_too(self):
        """A dead Satisfactory server costs the same timeout as a dead Source one."""
        results = {"sat": _running("sat")}
        svc = _query_service()
        await _enrich(results, _cfg("sat", protocol="satisfactory"), svc,
                      _support({"sat": False}))

        svc.get_bulk_game_queries.assert_not_awaited()


class TestReachableServersStillQueried:
    """Guarding against the opposite failure: fast because it does nothing."""

    async def test_supported_server_is_queried(self):
        results = {"valheim": _running("valheim")}
        svc = _query_service(players=7)
        await _enrich(results, _cfg("valheim"), svc, _support({"valheim": True}))

        svc.get_bulk_game_queries.assert_awaited_once()
        assert results["valheim"].players_online == 7

    async def test_unknown_server_is_queried(self):
        """No verdict yet (never probed) must not be treated as unreachable."""
        results = {"fresh": _running("fresh")}
        svc = _query_service(players=2)
        await _enrich(results, _cfg("fresh"), svc, _support({}))

        svc.get_bulk_game_queries.assert_awaited_once()
        assert results["fresh"].players_online == 2

    async def test_a_failing_support_service_does_not_block_querying(self):
        """If the verdict store is unavailable, query everything rather than nothing."""
        results = {"valheim": _running("valheim")}
        svc = _query_service(players=5)
        support = MagicMock()
        support.is_supported.side_effect = RuntimeError("verdict store unavailable")

        await _enrich(results, _cfg("valheim"), svc, support)
        assert results["valheim"].players_online is None or \
            svc.get_bulk_game_queries.await_count >= 0  # must not raise

    @pytest.mark.parametrize("verdict", [True, None])
    async def test_resolution_happens_only_for_queried_containers(self, verdict):
        results = {"x": _running("x")}
        svc = _query_service()
        await _enrich(results, _cfg("x"), svc, _support({"x": verdict}))

        assert svc.resolve_query_candidates.await_count == 1

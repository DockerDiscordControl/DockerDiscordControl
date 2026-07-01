#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for StatusHandlersMixin._enrich_status_with_player_counts:
- global toggle off -> no-op (opengsq never touched)
- enriches only running, query-enabled containers
- failed/absent query leaves players_online = None (never breaks status)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cogs.status_handlers import StatusHandlersMixin
from services.docker_status.models import ContainerStatusResult
from services.infrastructure.game_query_service import GameQueryResult
from services.discord.embed_helper_service import format_player_line, format_player_inline


class TestPlayerLineRendering:
    """The user-visible embed line, shared by the status loop and the toggle path."""

    def test_count_with_max(self):
        assert format_player_line(3, 10, "Players") == "│ Players: 3/10\n"

    def test_count_without_max_has_no_slash(self):
        assert format_player_line(3, None, "Players") == "│ Players: 3\n"

    def test_zero_players_is_shown(self):
        assert format_player_line(0, 8, "Spieler") == "│ Spieler: 0/8\n"

    def test_no_data_is_empty_string(self):
        assert format_player_line(None, None, "Players") == ""
        assert format_player_line(None, 10, "Players") == ""

    def test_localized_label(self):
        assert format_player_line(2, 4, "Spieler") == "│ Spieler: 2/4\n"

    # Compact inline variant for the space-limited community overview (no emoji/label)
    def test_inline_with_max(self):
        assert format_player_inline(3, 8) == " 3/8"

    def test_inline_without_max(self):
        assert format_player_inline(3, None) == " 3"

    def test_inline_zero_players(self):
        assert format_player_inline(0, 8) == " 0/8"

    def test_inline_no_data_is_empty(self):
        assert format_player_inline(None, None) == ""
        assert format_player_inline(None, 8) == ""


def _running(name):
    return ContainerStatusResult.success_result(name, name, True, "1%", "1MB", "1m", True)


class TestPlayerEnrichment:
    async def test_flag_off_is_noop(self):
        mixin = StatusHandlersMixin()
        results = {"valheim": _running("valheim")}
        with patch('app.utils.web_helpers._get_advanced_setting', return_value=False), \
             patch('services.infrastructure.game_query_service.get_game_query_service') as gs:
            await mixin._enrich_status_with_player_counts(results, {"valheim": {"query_enabled": True}})
        gs.assert_not_called()
        assert results["valheim"].players_online is None

    async def test_enriches_running_query_enabled_only(self):
        mixin = StatusHandlersMixin()
        results = {"valheim": _running("valheim"), "nginx": _running("nginx")}
        cfg = {
            "valheim": {"query_enabled": True, "query_protocol": "source", "query_host": "", "query_port": 0},
            "nginx": {"query_enabled": False},
        }
        svc = MagicMock()
        svc.resolve_query_candidates = AsyncMock(return_value=("1.2.3.4", [2457]))
        svc.get_bulk_game_queries = AsyncMock(return_value={
            "valheim": GameQueryResult(success=True, container_name="valheim",
                                       players_online=3, max_players=10)})
        with patch('app.utils.web_helpers._get_advanced_setting', return_value=True), \
             patch('services.infrastructure.game_query_service.get_game_query_service', return_value=svc):
            await mixin._enrich_status_with_player_counts(results, cfg)
        assert results["valheim"].players_online == 3
        assert results["valheim"].max_players == 10
        assert results["nginx"].players_online is None        # not query-enabled
        assert svc.resolve_query_candidates.await_count == 1   # only valheim resolved

    async def test_request_carries_protocol_and_token(self):
        # cfg -> GameQueryRequest field mapping must thread protocol + token through
        mixin = StatusHandlersMixin()
        results = {"sat": _running("sat")}
        cfg = {"sat": {"query_enabled": True, "query_protocol": "satisfactory",
                       "query_host": "", "query_port": 0, "query_token": "APITOKEN"}}
        svc = MagicMock()
        svc.resolve_query_candidates = AsyncMock(return_value=("1.2.3.4", [7777, 7778]))
        svc.get_bulk_game_queries = AsyncMock(return_value={
            "sat": GameQueryResult(success=True, container_name="sat", players_online=1, max_players=4)})
        with patch('app.utils.web_helpers._get_advanced_setting', return_value=True), \
             patch('services.infrastructure.game_query_service.get_game_query_service', return_value=svc):
            await mixin._enrich_status_with_player_counts(results, cfg)
        targets = svc.get_bulk_game_queries.call_args.args[0]
        assert len(targets) == 1
        req = targets[0]
        assert req.protocol == "satisfactory"
        assert req.token == "APITOKEN"
        assert (req.host, req.port) == ("1.2.3.4", 7777)
        assert req.candidate_ports == (7778,)                  # extra ports become fallbacks
        # protocol is also passed into candidate resolution (4th positional arg)
        assert svc.resolve_query_candidates.await_args.args[3] == "satisfactory"

    async def test_uses_detected_protocol_for_minecraft(self):
        # config default is 'source' but detection found 'minecraft' -> query uses minecraft
        mixin = StatusHandlersMixin()
        results = {"mc": _running("mc")}
        cfg = {"mc": {"query_enabled": True, "query_protocol": "source", "query_host": "", "query_port": 0}}
        svc = MagicMock()
        svc.resolve_query_candidates = AsyncMock(return_value=("1.2.3.4", [25565]))
        svc.get_bulk_game_queries = AsyncMock(return_value={
            "mc": GameQueryResult(success=True, container_name="mc", players_online=5, max_players=20)})
        support = MagicMock()
        support.get_protocol.return_value = "minecraft"
        with patch('app.utils.web_helpers._get_advanced_setting', return_value=True), \
             patch('services.infrastructure.game_query_service.get_game_query_service', return_value=svc), \
             patch('services.infrastructure.game_query_support_service.get_game_query_support_service', return_value=support):
            await mixin._enrich_status_with_player_counts(results, cfg)
        req = svc.get_bulk_game_queries.call_args.args[0][0]
        assert req.protocol == "minecraft"
        assert svc.resolve_query_candidates.await_args.args[3] == "minecraft"

    async def test_no_targets_skips_bulk_query(self):
        mixin = StatusHandlersMixin()
        results = {"nginx": _running("nginx")}
        svc = MagicMock()
        svc.get_bulk_game_queries = AsyncMock()
        with patch('app.utils.web_helpers._get_advanced_setting', return_value=True), \
             patch('services.infrastructure.game_query_service.get_game_query_service', return_value=svc):
            await mixin._enrich_status_with_player_counts(results, {"nginx": {"query_enabled": False}})
        svc.get_bulk_game_queries.assert_not_called()

    async def test_failed_query_leaves_players_none(self):
        mixin = StatusHandlersMixin()
        results = {"valheim": _running("valheim")}
        svc = MagicMock()
        svc.resolve_query_candidates = AsyncMock(return_value=("1.2.3.4", [2457]))
        svc.get_bulk_game_queries = AsyncMock(return_value={
            "valheim": GameQueryResult(success=False, container_name="valheim", error_type="timeout")})
        with patch('app.utils.web_helpers._get_advanced_setting', return_value=True), \
             patch('services.infrastructure.game_query_service.get_game_query_service', return_value=svc):
            await mixin._enrich_status_with_player_counts(results, {"valheim": {"query_enabled": True}})
        assert results["valheim"].players_online is None

    async def test_stopped_container_not_queried(self):
        mixin = StatusHandlersMixin()
        stopped = ContainerStatusResult.offline_result("valheim", "valheim")
        results = {"valheim": stopped}
        svc = MagicMock()
        svc.resolve_query_candidates = AsyncMock()
        with patch('app.utils.web_helpers._get_advanced_setting', return_value=True), \
             patch('services.infrastructure.game_query_service.get_game_query_service', return_value=svc):
            await mixin._enrich_status_with_player_counts(results, {"valheim": {"query_enabled": True}})
        svc.resolve_query_candidates.assert_not_called()

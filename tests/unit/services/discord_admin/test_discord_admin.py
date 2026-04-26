# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Discord + Admin Services Unit Tests             #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""
Unit tests for:
- services.discord.channel_cleanup_service
- services.discord.status_overview_service
- services.admin.admin_service

Mocking strategy:
- AsyncMock for Discord async APIs (send/delete/purge/history/delete_messages)
- MagicMock for Channel / Message / User / Bot
- monkeypatch for filesystem-bound deps (admins.json) and the mech state
  manager singleton imported lazily inside StatusOverviewService.
- No sys.modules manipulation. No production code edits.
"""

import asyncio
import json
import sys
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest


# ---------------------------------------------------------------------------
# Import service modules. The conftest at tests/conftest.py pre-seeds a
# writable DDC_CONFIG_DIR so module-load chains succeed in dev.
# ---------------------------------------------------------------------------
from services.discord.channel_cleanup_service import (
    ChannelCleanupRequest,
    ChannelCleanupResult,
    ChannelCleanupService,
    get_channel_cleanup_service,
    reset_channel_cleanup_service,
)
from services.discord import status_overview_service as sov_module
from services.discord.status_overview_service import (
    StatusOverviewService,
    StatusOverviewUpdateConfig,
    UpdateDecision,
    get_status_overview_service,
    should_update_channel_overview,
    log_channel_update_decision,
)
import services.admin.admin_service as admin_mod
from services.admin.admin_service import AdminService, get_admin_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_async_iter(items):
    """Build a real async iterator (so `async for` works) from items."""

    class _AIter:
        def __init__(self, data):
            self._iter = iter(data)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration:
                raise StopAsyncIteration

    return _AIter(items)


def _make_message(
    *,
    msg_id: int = 1,
    author=None,
    bot_user=None,
    created_at=None,
    content: str = "",
    embeds=None,
):
    """Build a MagicMock that mimics a discord.Message."""
    msg = MagicMock(spec=discord.Message)
    msg.id = msg_id
    msg.author = author if author is not None else bot_user
    msg.created_at = (
        created_at
        if created_at is not None
        else datetime.now(timezone.utc) - timedelta(hours=1)
    )
    msg.content = content
    msg.embeds = embeds or []
    msg.delete = AsyncMock()
    return msg


def _make_channel(messages=None, *, channel_id: int = 1234):
    """Build a MagicMock channel whose .history is an async iterator."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id

    msgs = list(messages or [])
    # `channel.history(limit=...)` must return an async iterable.
    channel.history = MagicMock(side_effect=lambda *a, **kw: _make_async_iter(msgs))
    channel.delete_messages = AsyncMock()
    channel.purge = AsyncMock(return_value=msgs)
    channel.send = AsyncMock()
    return channel


def _make_bot(user_id: int = 999):
    """Build a fake bot whose .user is a MagicMock with id."""
    bot = MagicMock()
    bot_user = MagicMock(spec=discord.User)
    bot_user.id = user_id
    bot_user.bot = True
    bot.user = bot_user
    return bot


# ===========================================================================
# ChannelCleanupRequest / ChannelCleanupResult dataclass-ish smoke
# ===========================================================================
class TestCleanupRequestResult:
    def test_request_defaults(self):
        ch = _make_channel()
        req = ChannelCleanupRequest(channel=ch, reason="test")
        assert req.channel is ch
        assert req.reason == "test"
        assert req.message_limit == 100
        assert req.max_age_days == 30
        assert req.bot_only is True
        assert req.target_author is None
        assert req.custom_filter is None
        assert req.use_purge is False
        assert req.purge_timeout == 30.0

    def test_request_custom_args(self):
        ch = _make_channel()
        sentinel_filter = lambda m: True  # noqa: E731
        author = MagicMock(spec=discord.User)
        req = ChannelCleanupRequest(
            channel=ch,
            reason="custom",
            message_limit=50,
            max_age_days=7,
            bot_only=False,
            target_author=author,
            custom_filter=sentinel_filter,
            use_purge=True,
            purge_timeout=15.0,
        )
        assert req.message_limit == 50
        assert req.max_age_days == 7
        assert req.bot_only is False
        assert req.target_author is author
        assert req.custom_filter is sentinel_filter
        assert req.use_purge is True
        assert req.purge_timeout == 15.0

    def test_result_defaults(self):
        r = ChannelCleanupResult()
        assert r.success is False
        assert r.error is None
        assert r.messages_found == 0
        assert r.messages_deleted == 0
        assert r.bulk_deleted == 0
        assert r.individually_deleted == 0
        assert r.purge_deleted == 0
        assert r.permission_errors == 0
        assert r.not_found_errors == 0
        assert r.timeout_errors == 0
        assert r.messages_preserved == 0
        assert r.execution_time_ms == 0.0
        assert r.method_used == "unknown"


# ===========================================================================
# ChannelCleanupService
# ===========================================================================
class TestChannelCleanupServiceCore:
    def test_init_logs(self):
        bot = _make_bot()
        svc = ChannelCleanupService(bot)
        assert svc.bot is bot

    @pytest.mark.asyncio
    async def test_cleanup_empty_channel_succeeds(self):
        bot = _make_bot()
        ch = _make_channel(messages=[])
        svc = ChannelCleanupService(bot)
        result = await svc.cleanup_channel(
            ChannelCleanupRequest(channel=ch, reason="empty")
        )
        assert result.success is True
        assert result.messages_found == 0
        assert result.messages_deleted == 0
        # execution_time_ms is set in `finally`
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_collect_skips_old_messages_by_age(self):
        bot = _make_bot()
        old = _make_message(
            msg_id=1,
            author=bot.user,
            created_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        recent = _make_message(
            msg_id=2,
            author=bot.user,
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        ch = _make_channel(messages=[old, recent])
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(channel=ch, reason="age", max_age_days=30)
        result = ChannelCleanupResult()
        msgs = await svc._collect_messages(req, result)
        ids = [m.id for m in msgs]
        assert 1 not in ids
        assert 2 in ids

    @pytest.mark.asyncio
    async def test_collect_filters_by_bot_only(self):
        bot = _make_bot()
        other_user = MagicMock(spec=discord.User)
        other_user.id = 42
        bot_msg = _make_message(msg_id=10, author=bot.user)
        user_msg = _make_message(msg_id=11, author=other_user)
        ch = _make_channel(messages=[bot_msg, user_msg])
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(channel=ch, reason="botonly", bot_only=True)
        result = ChannelCleanupResult()
        msgs = await svc._collect_messages(req, result)
        assert [m.id for m in msgs] == [10]

    @pytest.mark.asyncio
    async def test_collect_filters_by_target_author(self):
        bot = _make_bot()
        target = MagicMock(spec=discord.User)
        target.id = 77
        m_target = _make_message(msg_id=20, author=target)
        m_other = _make_message(msg_id=21, author=bot.user)
        ch = _make_channel(messages=[m_target, m_other])
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(
            channel=ch,
            reason="target",
            bot_only=False,
            target_author=target,
        )
        result = ChannelCleanupResult()
        msgs = await svc._collect_messages(req, result)
        assert [m.id for m in msgs] == [20]

    @pytest.mark.asyncio
    async def test_collect_custom_filter_preserves(self):
        bot = _make_bot()
        m1 = _make_message(msg_id=30, author=bot.user, content="keep")
        m2 = _make_message(msg_id=31, author=bot.user, content="delete")
        ch = _make_channel(messages=[m1, m2])
        svc = ChannelCleanupService(bot)

        def custom(msg):
            return msg.content == "delete"

        req = ChannelCleanupRequest(
            channel=ch,
            reason="cf",
            bot_only=True,
            custom_filter=custom,
        )
        result = ChannelCleanupResult()
        msgs = await svc._collect_messages(req, result)
        assert [m.id for m in msgs] == [31]
        assert result.messages_preserved == 1

    @pytest.mark.asyncio
    async def test_bulk_delete_single_message(self):
        bot = _make_bot()
        msg = _make_message(msg_id=40, author=bot.user)
        ch = _make_channel(messages=[msg])
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(channel=ch, reason="single")
        result = ChannelCleanupResult()
        await svc._bulk_delete_messages(req, [msg], result)
        assert result.bulk_deleted == 1
        msg.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_bulk_delete_multiple_messages_uses_channel(self):
        bot = _make_bot()
        msgs = [_make_message(msg_id=i, author=bot.user) for i in range(50, 53)]
        ch = _make_channel(messages=msgs)
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(channel=ch, reason="bulk")
        result = ChannelCleanupResult()
        await svc._bulk_delete_messages(req, msgs, result)
        assert result.bulk_deleted == 3
        ch.delete_messages.assert_awaited_once_with(msgs)

    @pytest.mark.asyncio
    async def test_bulk_delete_falls_back_on_forbidden(self):
        bot = _make_bot()
        msgs = [_make_message(msg_id=i, author=bot.user) for i in range(60, 62)]
        ch = _make_channel(messages=msgs)
        ch.delete_messages = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "no perm"))
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(channel=ch, reason="forbid")
        result = ChannelCleanupResult()
        await svc._bulk_delete_messages(req, msgs, result)
        # Forbidden -> fallback individual
        assert result.permission_errors == 1
        # Each message had .delete called individually as fallback
        for m in msgs:
            m.delete.assert_awaited_once()
        assert result.individually_deleted == 2

    @pytest.mark.asyncio
    async def test_bulk_delete_falls_back_on_http_error(self):
        bot = _make_bot()
        msgs = [_make_message(msg_id=i, author=bot.user) for i in range(70, 72)]
        ch = _make_channel(messages=msgs)
        ch.delete_messages = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=400), "boom"))
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(channel=ch, reason="http")
        result = ChannelCleanupResult()
        await svc._bulk_delete_messages(req, msgs, result)
        # HTTPException -> fallback individual (no permission_errors increment)
        assert result.individually_deleted == 2

    @pytest.mark.asyncio
    async def test_individual_delete_handles_not_found(self):
        bot = _make_bot()
        m1 = _make_message(msg_id=80, author=bot.user)
        m1.delete = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "gone"))
        m2 = _make_message(msg_id=81, author=bot.user)
        ch = _make_channel(messages=[m1, m2])
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(channel=ch, reason="ind")
        result = ChannelCleanupResult()
        await svc._individual_delete_messages(req, [m1, m2], result)
        # NotFound counts as deleted (treated as success)
        assert result.individually_deleted == 2
        assert result.not_found_errors == 1

    @pytest.mark.asyncio
    async def test_individual_delete_handles_forbidden(self):
        bot = _make_bot()
        m1 = _make_message(msg_id=90, author=bot.user)
        m1.delete = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "no"))
        ch = _make_channel(messages=[m1])
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(channel=ch, reason="ind-forbid")
        result = ChannelCleanupResult()
        await svc._individual_delete_messages(req, [m1], result)
        assert result.permission_errors == 1
        assert result.individually_deleted == 0

    @pytest.mark.asyncio
    async def test_delete_messages_splits_old_and_recent(self):
        bot = _make_bot()
        recent = _make_message(
            msg_id=100,
            author=bot.user,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        old = _make_message(
            msg_id=101,
            author=bot.user,
            created_at=datetime.now(timezone.utc) - timedelta(days=20),
        )
        ch = _make_channel(messages=[recent, old])
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(channel=ch, reason="split")
        result = ChannelCleanupResult()
        await svc._delete_messages(req, [recent, old], result)
        # Recent: bulk_deleted == 1 (single message path)
        assert result.bulk_deleted == 1
        # Old: individually deleted
        assert result.individually_deleted == 1
        old.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_full_cleanup_channel_happy_path(self):
        bot = _make_bot()
        msgs = [
            _make_message(msg_id=i, author=bot.user)
            for i in range(110, 113)
        ]
        ch = _make_channel(messages=msgs)
        svc = ChannelCleanupService(bot)

        result = await svc.cleanup_channel(
            ChannelCleanupRequest(channel=ch, reason="full")
        )
        assert result.success is True
        assert result.messages_found == 3
        assert result.messages_deleted == 3
        ch.delete_messages.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_channel_handles_collect_exception(self):
        bot = _make_bot()
        ch = _make_channel()

        async def _raising(*a, **k):
            # async generator that raises on first iteration
            raise RuntimeError("history broke")
            yield  # pragma: no cover (unreachable)

        ch.history = MagicMock(side_effect=lambda *a, **k: _raising())
        svc = ChannelCleanupService(bot)

        result = await svc.cleanup_channel(
            ChannelCleanupRequest(channel=ch, reason="boom")
        )
        assert result.success is False
        assert result.error is not None
        assert "history broke" in result.error

    @pytest.mark.asyncio
    async def test_clean_sweep_bot_messages_uses_bot_user(self):
        bot = _make_bot()
        msg = _make_message(msg_id=120, author=bot.user)
        ch = _make_channel(messages=[msg])
        svc = ChannelCleanupService(bot)

        result = await svc.clean_sweep_bot_messages(ch, reason="sweep")
        assert result.success is True
        assert result.messages_found == 1

    @pytest.mark.asyncio
    async def test_purge_with_filter_success(self):
        bot = _make_bot()
        msgs = [_make_message(msg_id=i, author=bot.user) for i in range(130, 133)]
        ch = _make_channel(messages=msgs)
        # purge returns the deleted messages
        ch.purge = AsyncMock(return_value=msgs)
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(
            channel=ch,
            reason="purge",
            use_purge=True,
            custom_filter=lambda m: True,
        )
        result = ChannelCleanupResult()
        await svc._purge_with_filter(req, result)
        assert result.purge_deleted == 3
        assert result.method_used == "Discord purge API"
        ch.purge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_purge_with_filter_timeout_fallback(self):
        bot = _make_bot()
        # In fallback path we iterate channel.history again
        m_target = _make_message(msg_id=140, author=bot.user, content="del")
        ch = _make_channel(messages=[m_target])
        ch.purge = AsyncMock(side_effect=asyncio.TimeoutError())
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(
            channel=ch,
            reason="purge-timeout",
            use_purge=True,
            custom_filter=lambda m: True,
            purge_timeout=0.01,
        )
        result = ChannelCleanupResult()
        await svc._purge_with_filter(req, result)
        assert result.timeout_errors == 1
        assert "fallback" in result.method_used
        assert result.individually_deleted == 1
        m_target.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_purge_with_filter_forbidden(self):
        bot = _make_bot()
        ch = _make_channel(messages=[])
        ch.purge = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "no"))
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(
            channel=ch,
            reason="purge-forbidden",
            use_purge=True,
            custom_filter=lambda m: True,
        )
        result = ChannelCleanupResult()
        await svc._purge_with_filter(req, result)
        assert result.permission_errors == 1
        assert "forbidden" in result.method_used

    @pytest.mark.asyncio
    async def test_purge_with_filter_http_error_reraises(self):
        bot = _make_bot()
        ch = _make_channel()
        ch.purge = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "boom"))
        svc = ChannelCleanupService(bot)

        req = ChannelCleanupRequest(
            channel=ch,
            reason="purge-http",
            use_purge=True,
            custom_filter=lambda m: True,
        )
        result = ChannelCleanupResult()
        with pytest.raises(discord.HTTPException):
            await svc._purge_with_filter(req, result)
        assert "purge error" in result.method_used

    @pytest.mark.asyncio
    async def test_delete_bot_messages_preserve_live_logs_filter(self):
        bot = _make_bot()
        # Live Log message via embed title
        live_log_msg = MagicMock(spec=discord.Message)
        live_log_msg.id = 200
        live_log_msg.author = bot.user
        live_log_msg.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
        live_log_msg.content = ""
        embed = MagicMock()
        embed.title = "🔍 Live Logs"
        embed.footer = MagicMock()
        embed.footer.text = ""
        live_log_msg.embeds = [embed]
        live_log_msg.delete = AsyncMock()

        # AAS preserved message
        aas_msg = _make_message(
            msg_id=201,
            author=bot.user,
            content="⚡ `start` **container** — *RuleName*",
        )

        # Regular bot message that SHOULD be deleted
        plain = _make_message(msg_id=202, author=bot.user, content="hello")

        ch = _make_channel(messages=[live_log_msg, aas_msg, plain])
        ch.purge = AsyncMock(return_value=[plain])
        svc = ChannelCleanupService(bot)

        result = await svc.delete_bot_messages_preserve_live_logs(ch, reason="live")
        assert result.success is True
        # purge_deleted == 1 (only the plain message survives the filter)
        assert result.purge_deleted == 1
        assert result.method_used == "Discord purge API"

    @pytest.mark.asyncio
    async def test_preserve_live_logs_filter_via_footer(self):
        bot = _make_bot()
        msg = MagicMock(spec=discord.Message)
        msg.id = 210
        msg.author = bot.user
        msg.content = ""
        msg.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
        embed = MagicMock()
        embed.title = "Some title"
        embed.footer = MagicMock()
        embed.footer.text = "Auto-refreshing every 5s"
        msg.embeds = [embed]
        msg.delete = AsyncMock()

        plain = _make_message(msg_id=211, author=bot.user, content="x")

        ch = _make_channel(messages=[msg, plain])

        # Capture the filter that is built and passed to purge
        captured = {}

        async def _fake_purge(*, limit, check):
            captured["check"] = check
            kept = [m for m in [msg, plain] if check(m)]
            return kept

        ch.purge = AsyncMock(side_effect=_fake_purge)

        svc = ChannelCleanupService(bot)
        result = await svc.delete_bot_messages_preserve_live_logs(ch, reason="footer")
        assert result.success is True
        check = captured["check"]
        assert check(msg) is False  # preserved by footer
        assert check(plain) is True


class TestChannelCleanupSingleton:
    def setup_method(self):
        reset_channel_cleanup_service()

    def teardown_method(self):
        reset_channel_cleanup_service()

    def test_get_requires_bot_first_time(self):
        with pytest.raises(ValueError):
            get_channel_cleanup_service()

    def test_get_returns_singleton(self):
        bot = _make_bot()
        a = get_channel_cleanup_service(bot)
        b = get_channel_cleanup_service()
        assert a is b


# ===========================================================================
# StatusOverviewService
# ===========================================================================
class _StubMechStateManager:
    def __init__(self, force_recreate=False):
        self._force = force_recreate
        self.calls: List[str] = []

    def should_force_recreate(self, channel_id: str) -> bool:
        self.calls.append(channel_id)
        return self._force


@pytest.fixture
def patched_mech_state_manager(monkeypatch):
    """Replace get_mech_state_manager so StatusOverviewService doesn't pull
    in the real subsystem during tests. Lazy-imported inside the service,
    so we monkeypatch the source module."""
    stub = _StubMechStateManager(force_recreate=False)

    import services.mech.mech_state_manager as msm

    monkeypatch.setattr(msm, "get_mech_state_manager", lambda: stub)
    return stub


class TestStatusOverviewService:
    def test_force_refresh_returns_should_update(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        decision = svc.make_update_decision(
            channel_id=1,
            global_config={},
            force_refresh=True,
        )
        assert decision.should_update is True
        assert decision.should_recreate is False
        assert decision.reason.startswith("force_refresh_")

    def test_force_refresh_with_force_recreate(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        decision = svc.make_update_decision(
            channel_id=1,
            global_config={},
            force_refresh=True,
            force_recreate=True,
        )
        assert decision.should_update is True
        assert decision.should_recreate is True

    def test_auto_refresh_disabled_skips(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        global_config = {
            "default_channel_permissions": {"enable_auto_refresh": False},
        }
        decision = svc.make_update_decision(channel_id=1, global_config=global_config)
        assert decision.should_update is False
        assert decision.reason == "auto_refresh_disabled_in_web_ui"
        assert decision.skip_reason

    def test_interval_not_reached_skips(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        last_update = datetime.now(timezone.utc) - timedelta(minutes=1)
        global_config = {
            "default_channel_permissions": {
                "enable_auto_refresh": True,
                "update_interval_minutes": 10,
                "recreate_messages_on_inactivity": False,
            }
        }
        decision = svc.make_update_decision(
            channel_id=2,
            global_config=global_config,
            last_update_time=last_update,
        )
        assert decision.should_update is False
        assert "interval_not_reached" in decision.reason

    def test_interval_reached_updates(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        last_update = datetime.now(timezone.utc) - timedelta(minutes=20)
        global_config = {
            "default_channel_permissions": {
                "enable_auto_refresh": True,
                "update_interval_minutes": 10,
                "recreate_messages_on_inactivity": False,
            }
        }
        decision = svc.make_update_decision(
            channel_id=3,
            global_config=global_config,
            last_update_time=last_update,
        )
        assert decision.should_update is True
        assert decision.should_recreate is False
        assert "interval_reached" in decision.reason

    def test_recreate_via_inactivity(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        last_update = datetime.now(timezone.utc) - timedelta(minutes=1)
        last_activity = datetime.now(timezone.utc) - timedelta(minutes=30)
        global_config = {
            "default_channel_permissions": {
                "enable_auto_refresh": True,
                "update_interval_minutes": 10,
                "recreate_messages_on_inactivity": True,
                "inactivity_timeout_minutes": 10,
            }
        }
        decision = svc.make_update_decision(
            channel_id=4,
            global_config=global_config,
            last_update_time=last_update,
            last_channel_activity=last_activity,
        )
        # Even though interval not reached, recreation flips should_update True
        assert decision.should_update is True
        assert decision.should_recreate is True

    def test_recreate_via_mech_force(self, monkeypatch):
        # Use a custom stub that forces recreation
        stub = _StubMechStateManager(force_recreate=True)
        import services.mech.mech_state_manager as msm

        monkeypatch.setattr(msm, "get_mech_state_manager", lambda: stub)

        svc = StatusOverviewService()
        last_update = datetime.now(timezone.utc) - timedelta(minutes=1)
        global_config = {
            "default_channel_permissions": {
                "enable_auto_refresh": True,
                "update_interval_minutes": 10,
                "recreate_messages_on_inactivity": True,
                "inactivity_timeout_minutes": 10,
            }
        }
        decision = svc.make_update_decision(
            channel_id=5,
            global_config=global_config,
            last_update_time=last_update,
        )
        assert decision.should_update is True
        assert decision.should_recreate is True
        assert "5" in stub.calls

    def test_force_recreate_short_circuit(self, patched_mech_state_manager):
        # _should_recreate_message returns True immediately when force_recreate
        svc = StatusOverviewService()
        cfg = StatusOverviewUpdateConfig(recreate_messages_on_inactivity=False)
        assert svc._should_recreate_message(7, cfg, force_recreate=True) is True

    def test_should_recreate_disabled_returns_false(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        cfg = StatusOverviewUpdateConfig(recreate_messages_on_inactivity=False)
        assert svc._should_recreate_message(8, cfg, force_recreate=False) is False

    def test_calculate_next_check_time_with_last(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        cfg = StatusOverviewUpdateConfig(update_interval_minutes=15)
        last = datetime.now(timezone.utc)
        nxt = svc._calculate_next_check_time(last, cfg)
        assert nxt is not None
        assert (nxt - last) == timedelta(minutes=15)

    def test_calculate_next_check_time_none(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        cfg = StatusOverviewUpdateConfig()
        assert svc._calculate_next_check_time(None, cfg) is None

    def test_get_channel_update_config_falls_back_to_default(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        global_config = {
            "default_channel_permissions": {
                "enable_auto_refresh": False,
                "update_interval_minutes": 7,
                "recreate_messages_on_inactivity": False,
                "inactivity_timeout_minutes": 3,
            }
        }
        cfg = svc._get_channel_update_config(1234567, global_config)
        assert cfg.enable_auto_refresh is False
        assert cfg.update_interval_minutes == 7
        assert cfg.recreate_messages_on_inactivity is False
        assert cfg.inactivity_timeout_minutes == 3

    def test_get_channel_update_config_uses_specific_override(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        global_config = {
            "default_channel_permissions": {
                "enable_auto_refresh": True,
                "update_interval_minutes": 10,
            },
            "channel_permissions": {
                "999": {
                    "enable_auto_refresh": False,
                    "update_interval_minutes": 30,
                },
            },
        }
        cfg = svc._get_channel_update_config(999, global_config)
        assert cfg.enable_auto_refresh is False
        assert cfg.update_interval_minutes == 30

    def test_config_caching(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        global_config = {
            "default_channel_permissions": {
                "enable_auto_refresh": True,
                "update_interval_minutes": 10,
            }
        }
        # First call populates cache
        cfg1 = svc._get_channel_update_config(50, global_config)
        # Mutate global_config; if cache is honoured, returned config stays same
        global_config["default_channel_permissions"]["update_interval_minutes"] = 99
        cfg2 = svc._get_channel_update_config(50, global_config)
        assert cfg2.update_interval_minutes == cfg1.update_interval_minutes == 10

    def test_get_channel_config_summary(self, patched_mech_state_manager):
        svc = StatusOverviewService()
        global_config = {
            "default_channel_permissions": {
                "enable_auto_refresh": True,
                "update_interval_minutes": 5,
            }
        }
        summary = svc.get_channel_config_summary(11, global_config)
        assert summary["channel_id"] == 11
        assert summary["enable_auto_refresh"] is True
        assert summary["update_interval_minutes"] == 5
        assert summary["config_source"] in {"cached", "fresh"}

    def test_should_update_channel_overview_helper(self, monkeypatch, patched_mech_state_manager):
        # Reset the singleton in the module so we get a fresh instance
        monkeypatch.setattr(sov_module, "_status_overview_service", None)
        global_config = {
            "default_channel_permissions": {
                "enable_auto_refresh": True,
                "update_interval_minutes": 10,
                "recreate_messages_on_inactivity": False,
            }
        }
        flag, reason = should_update_channel_overview(
            channel_id=42,
            global_config=global_config,
            last_update_time=datetime.now(timezone.utc) - timedelta(minutes=20),
        )
        assert flag is True
        assert isinstance(reason, str)

    def test_log_channel_update_decision_runs(self, monkeypatch, patched_mech_state_manager, caplog):
        monkeypatch.setattr(sov_module, "_status_overview_service", None)
        global_config = {
            "default_channel_permissions": {
                "enable_auto_refresh": True,
                "update_interval_minutes": 10,
            }
        }
        # Should not raise even with no last_update_time
        log_channel_update_decision(channel_id=42, global_config=global_config)

    def test_get_status_overview_service_singleton(self, monkeypatch):
        monkeypatch.setattr(sov_module, "_status_overview_service", None)
        a = get_status_overview_service()
        b = get_status_overview_service()
        assert a is b

    def test_make_update_decision_error_fallback(self, monkeypatch, patched_mech_state_manager):
        svc = StatusOverviewService()
        # Force the internal _get_channel_update_config to raise RuntimeError
        def boom(*a, **k):
            raise RuntimeError("config failure")

        monkeypatch.setattr(svc, "_get_channel_update_config", boom)
        decision = svc.make_update_decision(channel_id=1, global_config={})
        # On RuntimeError -> safe fallback: should_update True
        assert decision.should_update is True
        assert decision.should_recreate is False
        assert decision.reason.startswith("error_fallback_")


# ===========================================================================
# AdminService
# ===========================================================================
@pytest.fixture
def fake_project_root(tmp_path, monkeypatch):
    """Build a fake project tree where Path(__file__).parents[2] resolves to
    a tmp dir we control, then point AdminService at it via monkeypatching
    the module-level Path used inside _load_admin_users / get_admin_data /
    save_admin_data.

    We cannot easily change Path(__file__) inside admin_service. Instead we
    monkey-patch the resolved file path by pre-creating the config dir at
    the real project root's .../tests-isolated location is impossible.

    Workaround: the `parents[2]` chain in admin_service uses
    services/admin/admin_service.py as anchor → project root is the actual
    repo dir. We therefore patch open() and Path.exists for admins.json
    selectively in each test instead of redirecting the whole base_dir.
    """
    return tmp_path


def _stub_load_config(monkeypatch, return_value=None):
    """Stub the deferred import of services.config.config_service.load_config."""
    fake = types.ModuleType("services.config.config_service_test_stub")
    fake.load_config = lambda: (return_value if return_value is not None else {"foo": "bar"})

    # Patch the real config_service.load_config
    import services.config.config_service as cs
    monkeypatch.setattr(cs, "load_config", fake.load_config, raising=True)


class TestAdminServiceCacheAndLoad:
    def test_init_state(self):
        svc = AdminService()
        assert svc._admin_users_cache is None
        assert svc._cache_timestamp is None
        assert svc._cache_ttl == timedelta(minutes=5)

    def test_is_cache_valid_false_when_none(self):
        svc = AdminService()
        assert svc._is_cache_valid() is False

    def test_is_cache_valid_true_within_ttl(self):
        svc = AdminService()
        svc._admin_users_cache = ["1", "2"]
        svc._cache_timestamp = datetime.now()
        assert svc._is_cache_valid() is True

    def test_is_cache_valid_false_after_ttl(self):
        svc = AdminService()
        svc._admin_users_cache = ["1"]
        svc._cache_timestamp = datetime.now() - timedelta(minutes=10)
        assert svc._is_cache_valid() is False

    def test_get_admin_users_returns_cache_when_valid(self, monkeypatch):
        svc = AdminService()
        svc._admin_users_cache = ["111", "222"]
        svc._cache_timestamp = datetime.now()

        # _load_admin_users must NOT be called
        called = {"n": 0}

        def boom():
            called["n"] += 1
            return ["DIFFERENT"]

        monkeypatch.setattr(svc, "_load_admin_users", boom)
        result = svc.get_admin_users()
        assert result == ["111", "222"]
        assert called["n"] == 0

    def test_get_admin_users_force_refresh_calls_load(self, monkeypatch):
        svc = AdminService()
        svc._admin_users_cache = ["old"]
        svc._cache_timestamp = datetime.now()

        called = {"n": 0}

        def fake_load():
            called["n"] += 1
            return ["new1", "new2"]

        monkeypatch.setattr(svc, "_load_admin_users", fake_load)
        result = svc.get_admin_users(force_refresh=True)
        assert result == ["new1", "new2"]
        assert called["n"] == 1

    def test_clear_cache(self):
        svc = AdminService()
        svc._admin_users_cache = ["1"]
        svc._cache_timestamp = datetime.now()
        svc.clear_cache()
        assert svc._admin_users_cache is None
        assert svc._cache_timestamp is None

    def test_is_user_admin_true(self, monkeypatch):
        svc = AdminService()
        monkeypatch.setattr(svc, "get_admin_users", lambda force_refresh=False: ["111", "222"])
        assert svc.is_user_admin("111") is True
        assert svc.is_user_admin(222) is True

    def test_is_user_admin_false(self, monkeypatch):
        svc = AdminService()
        monkeypatch.setattr(svc, "get_admin_users", lambda force_refresh=False: ["111"])
        assert svc.is_user_admin("999") is False
        assert svc.is_user_admin(7) is False


class TestAdminServiceFileIO:
    """Cover _load_admin_users / get_admin_data / save_admin_data via file mocking."""

    def _patch_admins_path(self, monkeypatch, tmp_path):
        """Make admin_service look at tmp_path/config/admins.json instead of
        the real project root.

        We can't rewrite Path(__file__).parents[2] cleanly, so we patch the
        Path class used within the module: redirect any reference to
        '.../config/admins.json' through a tmp dir.

        Strategy: monkey-patch `Path` inside admin_service module so the
        constructor with __file__ produces a stub object whose
        `parents[2] / 'config' / 'admins.json'` resolves into tmp_path.
        """
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        admins_file = config_dir / "admins.json"

        real_path = admin_mod.Path

        class _FakePath(type(real_path("/"))):
            # We want only the call `Path(__file__)` to be redirected.
            def __new__(cls, *args, **kwargs):
                # Accept anything but always rebuild from real Path
                return real_path.__new__(real_path, *args, **kwargs)

        # Simpler: just patch admin_mod.Path with a callable that returns a
        # stub for the __file__ argument, otherwise the real Path.
        def _fake_path_ctor(arg=None, *args, **kwargs):
            if arg is not None and isinstance(arg, str) and arg.endswith("admin_service.py"):
                # Return an object whose `.parents[2]` is tmp_path
                anchor = real_path(arg)
                # Build a substitute parents list: [parent0, parent1, tmp_path]
                stub = MagicMock()
                stub.parents = [anchor.parent, anchor.parent.parent, tmp_path]
                return stub
            return real_path(arg, *args, **kwargs) if arg is not None else real_path(*args, **kwargs)

        monkeypatch.setattr(admin_mod, "Path", _fake_path_ctor)
        return admins_file

    def test_load_admin_users_missing_file_returns_empty(self, monkeypatch, tmp_path):
        admins_file = self._patch_admins_path(monkeypatch, tmp_path)
        # File does not exist
        assert not admins_file.exists()
        svc = AdminService()
        assert svc._load_admin_users() == []

    def test_load_admin_users_empty_file_returns_empty(self, monkeypatch, tmp_path):
        admins_file = self._patch_admins_path(monkeypatch, tmp_path)
        admins_file.write_text("   \n", encoding="utf-8")
        svc = AdminService()
        assert svc._load_admin_users() == []

    def test_load_admin_users_invalid_json(self, monkeypatch, tmp_path):
        admins_file = self._patch_admins_path(monkeypatch, tmp_path)
        admins_file.write_text("{not json", encoding="utf-8")
        svc = AdminService()
        assert svc._load_admin_users() == []

    def test_load_admin_users_valid_json(self, monkeypatch, tmp_path):
        admins_file = self._patch_admins_path(monkeypatch, tmp_path)
        admins_file.write_text(
            json.dumps({"discord_admin_users": [123, "456", 789]}),
            encoding="utf-8",
        )
        svc = AdminService()
        result = svc._load_admin_users()
        assert result == ["123", "456", "789"]

    def test_load_admin_users_skips_non_string_entries(self, monkeypatch, tmp_path):
        admins_file = self._patch_admins_path(monkeypatch, tmp_path)
        admins_file.write_text(
            json.dumps(
                {
                    "discord_admin_users": [
                        "123",
                        {"bad": "dict"},
                        ["nope"],
                        99,
                    ]
                }
            ),
            encoding="utf-8",
        )
        svc = AdminService()
        result = svc._load_admin_users()
        assert result == ["123", "99"]

    def test_get_admin_data_missing_file_returns_default(self, monkeypatch, tmp_path):
        self._patch_admins_path(monkeypatch, tmp_path)
        svc = AdminService()
        data = svc.get_admin_data()
        assert data == {"discord_admin_users": [], "admin_notes": {}}

    def test_get_admin_data_returns_full_payload(self, monkeypatch, tmp_path):
        admins_file = self._patch_admins_path(monkeypatch, tmp_path)
        admins_file.write_text(
            json.dumps(
                {
                    "discord_admin_users": ["1", "2"],
                    "admin_notes": {"1": "owner"},
                }
            ),
            encoding="utf-8",
        )
        svc = AdminService()
        data = svc.get_admin_data()
        assert data["discord_admin_users"] == ["1", "2"]
        assert data["admin_notes"] == {"1": "owner"}

    def test_get_admin_data_invalid_json_returns_default(self, monkeypatch, tmp_path):
        admins_file = self._patch_admins_path(monkeypatch, tmp_path)
        admins_file.write_text("{nope", encoding="utf-8")
        svc = AdminService()
        data = svc.get_admin_data()
        assert data == {"discord_admin_users": [], "admin_notes": {}}

    def test_save_admin_data_writes_file(self, monkeypatch, tmp_path):
        admins_file = self._patch_admins_path(monkeypatch, tmp_path)

        # Stub load_config -> truthy dict
        import services.config.config_service as cs
        monkeypatch.setattr(cs, "load_config", lambda: {"version": "test"})

        svc = AdminService()
        ok = svc.save_admin_data(["111", "222"], {"111": "alice"})
        assert ok is True
        assert admins_file.exists()
        on_disk = json.loads(admins_file.read_text(encoding="utf-8"))
        assert on_disk["discord_admin_users"] == ["111", "222"]
        assert on_disk["admin_notes"] == {"111": "alice"}
        # cache cleared
        assert svc._admin_users_cache is None
        assert svc._cache_timestamp is None

    def test_save_admin_data_returns_false_when_config_missing(self, monkeypatch, tmp_path):
        self._patch_admins_path(monkeypatch, tmp_path)
        import services.config.config_service as cs
        monkeypatch.setattr(cs, "load_config", lambda: None)

        svc = AdminService()
        assert svc.save_admin_data(["x"]) is False


class TestAdminServiceAsync:
    @pytest.mark.asyncio
    async def test_is_user_admin_async_true(self, monkeypatch):
        svc = AdminService()
        monkeypatch.setattr(svc, "is_user_admin", lambda uid, force_refresh=False: True)
        assert await svc.is_user_admin_async(999) is True

    @pytest.mark.asyncio
    async def test_get_admin_users_async_returns_list(self, monkeypatch):
        svc = AdminService()
        monkeypatch.setattr(svc, "get_admin_users", lambda force_refresh=False: ["a", "b"])
        result = await svc.get_admin_users_async()
        assert result == ["a", "b"]


class TestAdminServiceSingleton:
    def test_singleton(self, monkeypatch):
        # Reset singleton to ensure clean state
        monkeypatch.setattr(admin_mod, "_admin_service_instance", None)
        a = get_admin_service()
        b = get_admin_service()
        assert a is b
        assert isinstance(a, AdminService)

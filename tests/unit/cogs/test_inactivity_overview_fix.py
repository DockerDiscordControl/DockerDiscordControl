#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for the inactivity-loop "move overview to bottom" fix (FIX A) and the
by-ID overview deletion that prevents duplicate overviews (Schritt 0).

Covered:
- DockerControlCog._overview_buried_by_stray (FIX A decision predicate)
- DockerControlCog._delete_tracked_overview_messages (Schritt 0 by-ID delete)

The cog is instantiated via object.__new__ to bypass its heavy __init__ - both
methods under test only touch self.channel_server_message_ids (and, for delete,
the passed channel object).
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

import discord

from cogs.docker_control import DockerControlCog


def _make_cog(tracking):
    """Build a DockerControlCog without running __init__, with the given tracking dict."""
    cog = object.__new__(DockerControlCog)
    cog.channel_server_message_ids = tracking
    # mech_state_manager is always present in __init__; mock it so persistence is a no-op.
    cog.mech_state_manager = MagicMock()
    return cog


# ---------------------------------------------------------------------------
# FIX A: _overview_buried_by_stray
# ---------------------------------------------------------------------------

class TestOverviewBuriedByStray:
    def test_no_tracking_for_channel_returns_false(self):
        """Guard: no tracking (e.g. fresh after restart) -> never regenerate on a bot msg."""
        cog = _make_cog({})
        assert cog._overview_buried_by_stray(111, 999) is False

    def test_empty_tracking_dict_returns_false(self):
        cog = _make_cog({111: {}})
        assert cog._overview_buried_by_stray(111, 999) is False

    def test_only_none_ids_returns_false(self):
        """A tracked key mapped to None must not count as a managed id."""
        cog = _make_cog({111: {"overview": None}})
        assert cog._overview_buried_by_stray(111, 999) is False

    def test_last_message_is_tracked_overview_returns_false(self):
        """Overview is already at the bottom -> nothing to do."""
        cog = _make_cog({111: {"overview": 500}})
        assert cog._overview_buried_by_stray(111, 500) is False

    def test_last_message_is_tracked_admin_overview_returns_false(self):
        cog = _make_cog({111: {"admin_overview": 700}})
        assert cog._overview_buried_by_stray(111, 700) is False

    def test_stray_bot_message_below_overview_returns_true(self):
        """A stray bot message (different id) buried our overview -> move it down."""
        cog = _make_cog({111: {"overview": 500}})
        assert cog._overview_buried_by_stray(111, 999) is True

    def test_stray_below_admin_overview_returns_true(self):
        cog = _make_cog({111: {"admin_overview": 700}})
        assert cog._overview_buried_by_stray(111, 999) is True

    def test_matches_any_tracked_id_not_just_overview_keys(self):
        """Defensive: any tracked id (incl. legacy per-docker_name) counts as managed."""
        cog = _make_cog({111: {"overview": 500, "Enshrouded": 600}})
        assert cog._overview_buried_by_stray(111, 600) is False
        assert cog._overview_buried_by_stray(111, 999) is True


# ---------------------------------------------------------------------------
# Schritt 0: _delete_tracked_overview_messages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestDeleteTrackedOverviewMessages:
    def _make_channel(self):
        channel = MagicMock()
        channel.id = 111
        partial = MagicMock()
        partial.delete = AsyncMock()
        channel.get_partial_message = MagicMock(return_value=partial)
        return channel, partial

    async def test_no_tracking_is_noop(self):
        cog = _make_cog({})
        channel, partial = self._make_channel()
        await cog._delete_tracked_overview_messages(channel)
        partial.delete.assert_not_called()

    async def test_deletes_tracked_overview_by_id_and_pops(self):
        cog = _make_cog({111: {"overview": 500}})
        channel, partial = self._make_channel()
        await cog._delete_tracked_overview_messages(channel)
        channel.get_partial_message.assert_called_once_with(500)
        partial.delete.assert_awaited_once()
        assert "overview" not in cog.channel_server_message_ids[111]

    async def test_deletes_both_overview_and_admin_overview(self):
        cog = _make_cog({111: {"overview": 500, "admin_overview": 700}})
        channel, partial = self._make_channel()
        await cog._delete_tracked_overview_messages(channel)
        assert partial.delete.await_count == 2
        called_ids = {c.args[0] for c in channel.get_partial_message.call_args_list}
        assert called_ids == {500, 700}
        assert "overview" not in cog.channel_server_message_ids[111]
        assert "admin_overview" not in cog.channel_server_message_ids[111]

    async def test_notfound_is_swallowed_and_still_pops(self):
        cog = _make_cog({111: {"overview": 500}})
        channel, partial = self._make_channel()
        partial.delete = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "gone"))
        channel.get_partial_message = MagicMock(return_value=partial)
        # Must not raise
        await cog._delete_tracked_overview_messages(channel)
        assert "overview" not in cog.channel_server_message_ids[111]

    async def test_none_id_is_skipped(self):
        cog = _make_cog({111: {"overview": None}})
        channel, partial = self._make_channel()
        await cog._delete_tracked_overview_messages(channel)
        partial.delete.assert_not_called()

    async def test_transient_error_keeps_id_for_retry(self):
        # On a transient HTTPException the id must be KEPT so a later regenerate retries
        # the by-id delete (otherwise a >30-day-old overview is permanently stranded).
        cog = _make_cog({111: {"overview": 500}})
        channel, partial = self._make_channel()
        partial.delete = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "boom"))
        channel.get_partial_message = MagicMock(return_value=partial)
        await cog._delete_tracked_overview_messages(channel)  # must not raise
        assert cog.channel_server_message_ids[111].get("overview") == 500


# ---------------------------------------------------------------------------
# FIX C: _persist_tracked_message_ids snapshot
# ---------------------------------------------------------------------------

class TestPersistTrackedMessageIds:
    def _snapshot(self, tracking):
        cog = _make_cog(tracking)
        cog._persist_tracked_message_ids()
        # set_state(key, snapshot) -> grab the snapshot arg
        cog.mech_state_manager.set_state.assert_called_once()
        key, snapshot = cog.mech_state_manager.set_state.call_args.args
        assert key == "channel_overview_message_ids"
        return snapshot

    def test_persists_only_overview_keys_with_str_channel_ids(self):
        snap = self._snapshot({111: {"overview": 500}, 222: {"admin_overview": 700}})
        assert snap == {"111": {"overview": 500}, "222": {"admin_overview": 700}}

    def test_excludes_per_docker_and_none_ids(self):
        snap = self._snapshot({111: {"overview": 500, "Enshrouded": 600, "admin_overview": None}})
        assert snap == {"111": {"overview": 500}}

    def test_channel_with_no_overview_keys_is_dropped(self):
        snap = self._snapshot({111: {"Enshrouded": 600}})
        assert snap == {}


# ---------------------------------------------------------------------------
# FIX B: per-channel lock serialization
# ---------------------------------------------------------------------------

def _make_lock_cog():
    cog = object.__new__(DockerControlCog)
    cog._channel_locks = {}
    return cog


class TestGetChannelLock:
    def test_same_lock_per_channel_distinct_across_channels(self):
        cog = _make_lock_cog()
        l1 = cog._get_channel_lock(1)
        assert cog._get_channel_lock(1) is l1          # cached per channel
        assert cog._get_channel_lock(2) is not l1      # distinct per channel
        assert isinstance(l1, asyncio.Lock)


class TestRegenerateChannelSerialization:
    async def _run(self, ch_ids):
        """Drive _regenerate_channel concurrently for the given channel ids, recording the
        peak number of impl bodies running at once per channel and overall."""
        cog = _make_lock_cog()
        gauge = {"now": 0, "peak": 0}

        async def fake_impl(channel, mode, config):
            gauge["now"] += 1
            gauge["peak"] = max(gauge["peak"], gauge["now"])
            await asyncio.sleep(0.02)
            gauge["now"] -= 1

        cog._regenerate_channel_impl = fake_impl
        channels = [MagicMock(id=cid) for cid in ch_ids]
        await asyncio.gather(*(cog._regenerate_channel(c, "status", {}) for c in channels))
        return gauge["peak"]

    async def test_same_channel_never_runs_concurrently(self):
        peak = await self._run([7, 7, 7])
        assert peak == 1  # the lock serialized all three

    async def test_different_channels_run_in_parallel(self):
        peak = await self._run([1, 2, 3])
        assert peak == 3  # distinct locks -> no blocking

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Unit tests for cogs/control_helpers.py (was 52.7% covered).

Two of these are about access control and command registration, so getting them
wrong is expensive:

- ``_channel_has_permission`` decides whether a command may run in a channel.
  A default of True anywhere would open commands in channels nobody configured.
- ``get_guild_id`` decides whether slash commands register to one guild or
  globally, which changes how long Discord takes to publish them.

``_get_pending_embed`` is the placeholder shown while an action runs; its box
layout has a fixed width and must survive long container names.
"""

from unittest.mock import MagicMock

import discord
import pytest

import cogs.control_helpers as helpers
from cogs.control_helpers import (
    _channel_has_permission,
    _get_pending_embed,
    container_select,
    get_guild_id,
)


# ---------------------------------------------------------------------------
# get_guild_id
# ---------------------------------------------------------------------------

class TestGetGuildId:
    def test_configured_guild_is_returned_as_a_list(self, monkeypatch):
        """py-cord expects a list of guild ids, not a bare int."""
        monkeypatch.setattr(helpers, "get_cached_guild_id", lambda: 123456789)
        assert get_guild_id() == [123456789]

    @pytest.mark.parametrize("empty", [None, 0, ""])
    def test_missing_guild_falls_back_to_global_registration(self, monkeypatch, empty):
        monkeypatch.setattr(helpers, "get_cached_guild_id", lambda: empty)
        assert get_guild_id() is None

    def test_missing_guild_is_logged_as_a_warning(self, monkeypatch, caplog):
        """Global registration can take an hour to show up - that deserves a warning."""
        import logging

        monkeypatch.setattr(helpers, "get_cached_guild_id", lambda: None)
        with caplog.at_level(logging.WARNING):
            get_guild_id()
        assert any("globally" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# _channel_has_permission
# ---------------------------------------------------------------------------

def _config(*, channel=None, defaults=None):
    config = {}
    if channel is not None:
        config["channel_permissions"] = channel
    if defaults is not None:
        config["default_channel_permissions"] = defaults
    return config


class TestChannelPermission:
    def test_explicit_channel_permission_is_used(self):
        config = _config(channel={"111": {"commands": {"control": True}}})
        assert _channel_has_permission(111, "control", config) is True

    def test_explicit_denial_wins_over_permissive_defaults(self):
        """A channel configured explicitly must not inherit a permissive default."""
        config = _config(
            channel={"111": {"commands": {"control": False}}},
            defaults={"commands": {"control": True}},
        )
        assert _channel_has_permission(111, "control", config) is False

    def test_unconfigured_channel_falls_back_to_defaults(self):
        config = _config(defaults={"commands": {"control": True}})
        assert _channel_has_permission(999, "control", config) is True

    def test_missing_permission_key_denies(self):
        """Unknown command keys must never be allowed by accident."""
        config = _config(channel={"111": {"commands": {"other": True}}})
        assert _channel_has_permission(111, "control", config) is False

    def test_empty_config_denies(self):
        assert _channel_has_permission(111, "control", {}) is False

    def test_channel_id_is_matched_as_a_string(self):
        """Channel ids arrive as ints but are stored as strings in the config."""
        config = _config(channel={"222": {"commands": {"control": True}}})
        assert _channel_has_permission(222, "control", config) is True

    def test_config_is_loaded_when_none_is_passed(self, monkeypatch):
        monkeypatch.setattr(helpers, "load_config",
                            lambda: _config(defaults={"commands": {"control": True}}))
        assert _channel_has_permission(111, "control") is True


# ---------------------------------------------------------------------------
# _get_pending_embed
# ---------------------------------------------------------------------------

@pytest.fixture
def pending_env(monkeypatch):
    monkeypatch.setattr(helpers, "load_config", lambda: {"language": "en", "timezone": "UTC"})
    monkeypatch.setattr(helpers, "_", lambda text: text)
    monkeypatch.setattr(helpers, "format_datetime_with_timezone",
                        lambda dt, tz, time_only=False: "12:34")


class TestPendingEmbed:
    def test_returns_a_gold_embed(self, pending_env):
        embed = _get_pending_embed("alpha")
        assert isinstance(embed, discord.Embed)
        assert embed.color == discord.Color.gold()

    def test_contains_the_container_name_and_status(self, pending_env):
        embed = _get_pending_embed("alpha")
        assert "alpha" in embed.description
        assert "Pending..." in embed.description

    def test_timestamp_line_sits_above_the_code_block(self, pending_env):
        embed = _get_pending_embed("alpha")
        first_line = embed.description.split("\n")[0]
        assert first_line == "Pending since: 12:34"

    def test_footer_is_the_project_url(self, pending_env):
        assert _get_pending_embed("alpha").footer.text == "https://ddc.bot"

    def test_long_names_are_truncated_so_the_box_keeps_its_width(self, pending_env):
        """Without truncation a long name would break the drawn box."""
        embed = _get_pending_embed("a-very-long-container-name-that-overflows")
        header = [ln for ln in embed.description.split("\n") if ln.startswith("┌")][0]
        assert "…" in header
        assert len(header) <= 28

    def test_short_name_box_lines_have_the_same_width(self, pending_env):
        embed = _get_pending_embed("alpha")
        lines = embed.description.split("\n")
        header = [ln for ln in lines if ln.startswith("┌")][0]
        footer = [ln for ln in lines if ln.startswith("└")][0]
        assert len(header) == len(footer) == 28

    def test_empty_name_still_produces_a_valid_box(self, pending_env):
        embed = _get_pending_embed("")
        assert "┌" in embed.description and "└" in embed.description


# ---------------------------------------------------------------------------
# container_select
# ---------------------------------------------------------------------------

def _autocomplete_ctx(value):
    """Something that looks like an AutocompleteContext: it has .value and is no str."""
    ctx = MagicMock()
    ctx.value = value
    return ctx


@pytest.fixture
def servers(monkeypatch):
    holder = {"servers": []}
    monkeypatch.setattr(helpers, "get_cached_servers", lambda: holder["servers"])
    return holder


def _server(docker_name=None, **extra):
    entry = dict(extra)
    if docker_name is not None:
        entry["docker_name"] = docker_name
    return entry


class TestContainerSelectCallingConventions:
    """The handler is reached through both py-cord and discord.py style calls, and the
    search text sits in a different argument each time. Getting this wrong silently
    turns autocomplete into 'always show everything'."""

    async def test_pycord_style_context_in_the_second_argument(self, servers):
        servers["servers"] = [_server("minecraft"), _server("valheim")]
        assert await container_select(None, _autocomplete_ctx("val")) == ["valheim"]

    async def test_context_in_the_first_argument(self, servers):
        servers["servers"] = [_server("minecraft"), _server("valheim")]
        assert await container_select(_autocomplete_ctx("mine"), None) == ["minecraft"]

    async def test_discordpy_style_plain_string(self, servers):
        servers["servers"] = [_server("minecraft"), _server("valheim")]
        assert await container_select(object(), "valh") == ["valheim"]

    async def test_unknown_argument_shapes_fall_back_to_showing_everything(self, servers):
        """Better to offer all containers than none when the shape is unexpected."""
        servers["servers"] = [_server("minecraft"), _server("valheim")]
        assert await container_select(None, None) == ["minecraft", "valheim"]

    async def test_context_with_value_none_behaves_like_empty_input(self, servers):
        servers["servers"] = [_server("alpha")]
        assert await container_select(None, _autocomplete_ctx(None)) == ["alpha"]


class TestContainerSelectFiltering:
    async def test_no_servers_configured_yields_nothing(self, servers):
        assert await container_select(None, _autocomplete_ctx("")) == []

    async def test_entries_without_a_docker_name_are_skipped(self, servers):
        """A half-configured server would otherwise show up as None in the dropdown."""
        servers["servers"] = [_server("alpha"), _server(None, name="broken")]
        assert await container_select(None, _autocomplete_ctx("")) == ["alpha"]

    async def test_matching_is_case_insensitive(self, servers):
        servers["servers"] = [_server("MineCraft")]
        assert await container_select(None, _autocomplete_ctx("craft")) == ["MineCraft"]

    async def test_matching_is_a_substring_not_a_prefix(self, servers):
        servers["servers"] = [_server("game-valheim-01")]
        assert await container_select(None, _autocomplete_ctx("valheim")) == ["game-valheim-01"]

    async def test_no_match_yields_nothing(self, servers):
        servers["servers"] = [_server("alpha")]
        assert await container_select(None, _autocomplete_ctx("zzz")) == []

    async def test_result_respects_the_discord_limit(self, servers):
        """More than 25 choices makes Discord drop the whole response."""
        servers["servers"] = [_server(f"server-{i:03d}") for i in range(40)]
        assert len(await container_select(None, _autocomplete_ctx(""))) == 25

    async def test_configured_order_is_preserved(self, servers):
        servers["servers"] = [_server("zulu"), _server("alpha"), _server("mike")]
        assert await container_select(None, _autocomplete_ctx("")) == ["zulu", "alpha", "mike"]

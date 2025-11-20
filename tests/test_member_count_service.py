# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

import json
from pathlib import Path

import pytest

import services.config.config_service as config_module
import services.mech.progress_service as progress_module
from services.member_count import MemberCountService
from services.member_count import service as member_count_module
from services.mech.progress_paths import ProgressPaths


@pytest.fixture(autouse=True)
def reset_member_count_service(monkeypatch, tmp_path):
    """Ensure each test works with an isolated runtime."""

    def _fake_get_progress_paths():
        return ProgressPaths.from_base_dir(Path(tmp_path), create_missing=True)

    monkeypatch.setattr(member_count_module, "get_progress_paths", _fake_get_progress_paths)
    monkeypatch.setattr(config_module, "load_config", lambda: {})
    yield


class _StubProgressService:
    def __init__(self):
        self.updated_counts = []

    def update_member_count(self, value: int) -> None:
        self.updated_counts.append(value)


class _DummyMember:
    def __init__(self, identifier: int, *, bot: bool = False, system: bool = False):
        self.id = identifier
        self.bot = bot
        self.system = system


class _DummyChannel:
    def __init__(self, channel_id: int, name: str, members):
        self.id = channel_id
        self.name = name
        self.members = list(members)


class _DummyGuild:
    def __init__(self, member_count: int, channels):
        self.member_count = member_count
        self._channels = {channel.id: channel for channel in channels}

    def get_channel(self, channel_id: int):
        return self._channels.get(channel_id)


def _configure_channel_permissions(monkeypatch, config):
    monkeypatch.setattr(config_module, "load_config", lambda: config)


def test_compute_unique_member_count_filters_duplicates(monkeypatch):
    _configure_channel_permissions(
        monkeypatch,
        {
            "channel_permissions": {
                "100": {"commands": {"serverstatus": True}, "name": "Status A"},
                "200": {"commands": {"serverstatus": True}, "name": "Status B"},
            }
        },
    )

    channel_a = _DummyChannel(100, "status-a", [_DummyMember(1), _DummyMember(2), _DummyMember(1)])
    channel_b = _DummyChannel(200, "status-b", [_DummyMember(2), _DummyMember(3), _DummyMember(4, bot=True)])
    guild = _DummyGuild(member_count=99, channels=[channel_a, channel_b])

    service = MemberCountService()
    count = service.compute_unique_member_count(guild)

    assert count == 3


def test_compute_unique_member_count_uses_fallback_when_no_channels(monkeypatch):
    _configure_channel_permissions(monkeypatch, {"channel_permissions": {}})

    guild = _DummyGuild(member_count=42, channels=[])
    service = MemberCountService()

    count = service.compute_unique_member_count(guild)
    assert count == 42


@pytest.mark.asyncio
async def test_resolve_member_context_updates_progress(monkeypatch):
    _configure_channel_permissions(monkeypatch, {"channel_permissions": {}})

    progress_stub = _StubProgressService()
    monkeypatch.setattr(progress_module, "get_progress_service", lambda: progress_stub)

    guild = _DummyGuild(member_count=11, channels=[])

    class _DummyBot:
        def get_guild(self, guild_id: int):
            assert guild_id == 123
            return guild

    service = MemberCountService()
    resolved_guild, count = await service.resolve_member_context(_DummyBot(), "123", use_member_count=True)

    assert resolved_guild is guild
    assert count == 11
    assert progress_stub.updated_counts == [11]


def test_persist_member_count_snapshot_writes_file(tmp_path, monkeypatch):
    _configure_channel_permissions(monkeypatch, {"channel_permissions": {}})

    paths = ProgressPaths.from_base_dir(tmp_path, create_missing=True)
    monkeypatch.setattr(member_count_module, "get_progress_paths", lambda: paths)

    service = MemberCountService()
    service.persist_member_count_snapshot(
        7,
        source="status_channels",
        description="Unit test",
        note="Only a drill",
    )

    payload = json.loads(paths.member_count_file.read_text())
    assert payload["count"] == 7
    assert payload["source"] == "status_channels"
    assert payload["description"] == "Unit test"
    assert payload["note"] == "Only a drill"

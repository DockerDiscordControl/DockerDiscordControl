# -*- coding: utf-8 -*-
"""The channel copy in config.json is kept, and it is kept current.

THE FINDING (independent review of the web panel, 2026-09-23): one panel save
writes channel_permissions into config.json and then deletes it again.

    save_all_channels -> _update_main_config_bulk reads config.json, sets
        channel_permissions, rewrites the WHOLE file, and treats a failure
        there as a failed save, "because the bot reads the permissions from
        there"
    milliseconds later
    ConfigService.save_config pops channel_permissions out of the config it
        writes and rewrites the same file without it

Two things follow.

The documented recovery is dead. config_loader_service recovers channels from
config.json "if individual channel files are lost" - after any panel save
there is nothing there to recover from. A safety net that is removed by the
ordinary path is not a safety net; it is a comment.

And config.json has a second writer that takes no lock at all.
_update_main_config_bulk rewrites the whole file outside ConfigService's save
lock, so two overlapping saves - two tabs, a double-click - can have its write
land on top of save_config's and lose that save entirely.

The operator decided (2026-09-23) to make the net real rather than remove it:
config.json keeps a CURRENT copy, and both writers take the SAME lock.

HOW THIS TEST CAN FAIL: it saves channels, then saves the main config the way
a panel save does, and looks in config.json. No channel_permissions is red.

COUNTER-CHECK (2026-09-23): red before - the key was gone from config.json
after the second write. The other tests keep the copy honest: it follows a
later change, a save that carries no channels does not wipe it, and the
individual files stay the primary source.
"""

import json
import threading

import pytest

from services.config.channel_config_service import ChannelConfigService
from services.config.config_service import ConfigService


def _channel(name):
    return {"name": name, "commands": {"serverstatus": True}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    config_service = ConfigService()
    monkeypatch.setattr(config_service, "config_dir", tmp_path)
    monkeypatch.setattr(config_service, "main_config_file", tmp_path / "config.json")
    config_service.main_config_file.write_text(json.dumps({"timezone": "UTC"}),
                                               encoding="utf-8")

    channels = ChannelConfigService()
    monkeypatch.setattr(channels, "config_file", config_service.main_config_file)
    monkeypatch.setattr(channels, "channels_dir", tmp_path / "channels")
    channels.channels_dir.mkdir(parents=True, exist_ok=True)
    return config_service, channels


def _main_config(config_service):
    return json.loads(config_service.main_config_file.read_text(encoding="utf-8"))


def test_the_copy_survives_the_main_save(world):
    """THE FINDING: the second write deleted it again."""
    config_service, channels = world
    permissions = {"111111111111111111": _channel("announcements")}
    channels.save_all_channels(permissions)

    config_service.save_config({"timezone": "UTC", "channel_permissions": permissions})

    on_disk = _main_config(config_service)
    assert "channel_permissions" in on_disk, (
        "config.json has no channel copy after a panel save - the recovery path "
        "in config_loader_service has nothing to recover from")
    assert list(on_disk["channel_permissions"]) == ["111111111111111111"]


def test_the_copy_follows_a_later_change(world):
    """A stale copy would be worse than none: it would restore old rights."""
    config_service, channels = world
    channels.save_all_channels({"111111111111111111": _channel("first")})
    config_service.save_config({"timezone": "UTC"})

    channels.save_all_channels({"222222222222222222": _channel("second")})

    assert list(_main_config(config_service)["channel_permissions"]) == \
        ["222222222222222222"]


def test_a_save_without_channels_does_not_wipe_the_copy(world):
    """/set_ui_language and /setup save a config that carries no channels."""
    config_service, channels = world
    channels.save_all_channels({"111111111111111111": _channel("announcements")})

    config_service.save_config({"timezone": "Europe/Berlin"})

    on_disk = _main_config(config_service)
    assert list(on_disk.get("channel_permissions", {})) == ["111111111111111111"], (
        f"a save that said nothing about channels erased them: {on_disk}")


def test_the_two_writers_take_the_same_lock(world):
    """The second writer used to rewrite the whole file with no lock at all."""
    config_service, channels = world
    got_through = threading.Event()

    with config_service._save_lock:
        writer = threading.Thread(target=lambda: (
            channels.save_all_channels({"333333333333333333": _channel("late")}),
            got_through.set()))
        writer.start()
        slipped_in = got_through.wait(1.5)
    writer.join(10)

    assert not slipped_in, (
        "the channel writer rewrote config.json while the main save lock was "
        "held - two overlapping saves can lose one of them entirely")


def test_the_individual_files_are_still_the_source(world):
    """Counter-check: the copy is a fallback, not the truth."""
    config_service, channels = world
    channels.save_all_channels({"111111111111111111": _channel("announcements")})

    written = sorted(p.stem for p in channels.channels_dir.glob("*.json"))
    assert "111111111111111111" in written, written

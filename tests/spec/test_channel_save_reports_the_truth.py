# -*- coding: utf-8 -*-
"""Saving a channel says "saved" only when both files were written.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 11 F7, re-checked 2026-09-20):
``save_channel`` writes the per-channel file, then calls
``_update_main_config``, then returns True - whatever that second write did.
``_update_main_config`` catches its own I/O errors and returns None, so a
main config that cannot be written leaves no trace beyond one log line. The
main config is where the bot reads ``channel_permissions`` from, so the web
panel would report a saved permission that the bot never sees.
``delete_channel`` and ``save_all_channels`` do the same.
"""

import json

import pytest

CHANNEL = "123456789012345678"
PERMISSIONS = {"commands": {"control": True}, "post_initial": True}


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.config.channel_config_service import ChannelConfigService
    return ChannelConfigService()


def test_a_save_that_works_reports_success(service, tmp_path):
    """Premise: the normal case still says True and writes both files."""
    assert service.save_channel(CHANNEL, PERMISSIONS) is True

    assert (tmp_path / "channels" / f"{CHANNEL}.json").exists()
    main = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert main["channel_permissions"][CHANNEL] == PERMISSIONS


def test_a_main_config_that_cannot_be_written_is_not_a_success(service, tmp_path):
    # config.json as a directory: writing it fails the way a permission problem
    # on config/ would, which is the failure this project sees in practice.
    (tmp_path / "config.json").mkdir()

    assert service.save_channel(CHANNEL, PERMISSIONS) is False, (
        "the bot reads permissions from the main config, and it was not written"
    )


def test_a_delete_that_works_reports_success(service, tmp_path):
    """Counter-check: added after a mutation that reported every delete as failed
    went unnoticed - the suite only knew the failing case."""
    assert service.save_channel(CHANNEL, PERMISSIONS) is True

    assert service.delete_channel(CHANNEL) is True

    assert not (tmp_path / "channels" / f"{CHANNEL}.json").exists()
    main = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert CHANNEL not in main.get("channel_permissions", {})


def test_a_delete_that_cannot_reach_the_main_config_is_not_a_success(service, tmp_path):
    assert service.save_channel(CHANNEL, PERMISSIONS) is True
    (tmp_path / "config.json").unlink()
    (tmp_path / "config.json").mkdir()

    assert service.delete_channel(CHANNEL) is False, (
        "the channel file is gone but the main config still grants the permission"
    )

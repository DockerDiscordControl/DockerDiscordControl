# -*- coding: utf-8 -*-
"""A wrongly named leftover file does not overrule the real one.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 11 F6, re-checked 2026-09-20):
``get_all_channels`` migrates channel files whose name is not a Discord id.
When the correctly named file already exists, it deletes the wrongly named
duplicate - and then still does ``channels[channel_id] = channel_data`` with
the content it read from the file it just deleted. Whichever of the two the
directory listing yields last decides what the bot sees. This dict is the
channel permissions, so an old leftover named ``Control.json`` can quietly
grant or withhold a right that the real file does not.
"""

import json

import pytest

CHANNEL = "123456789012345678"
REAL = {"commands": {"control": True}, "post_initial": True, "source": "real file"}
LEFTOVER = {"channel_id": CHANNEL, "commands": {"control": False},
            "post_initial": False, "source": "leftover"}


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.config.channel_config_service import ChannelConfigService
    return ChannelConfigService()


def _write(service, name, data):
    (service.channels_dir / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_the_real_file_is_read(service):
    """Premise: with no leftover the real file is what comes back."""
    _write(service, CHANNEL, REAL)

    assert service.get_all_channels()[CHANNEL]["source"] == "real file"


def test_a_leftover_next_to_the_real_file_is_ignored(service):
    _write(service, CHANNEL, REAL)
    _write(service, "Control", LEFTOVER)

    channels = service.get_all_channels()

    assert channels[CHANNEL]["source"] == "real file", (
        "the deleted leftover decided what the bot sees"
    )
    assert channels[CHANNEL]["commands"]["control"] is True
    assert not (service.channels_dir / "Control.json").exists(), (
        "premise: the leftover is cleaned up"
    )


def test_a_leftover_without_a_real_file_is_still_migrated(service):
    """Counter-check: the migration itself must keep working."""
    _write(service, "Control", LEFTOVER)

    channels = service.get_all_channels()

    assert channels[CHANNEL]["source"] == "leftover"
    assert (service.channels_dir / f"{CHANNEL}.json").exists()

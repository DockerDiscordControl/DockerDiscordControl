# -*- coding: utf-8 -*-
"""A channel whose file cannot be read must not look like a channel that is gone.

THE FINDING (review E28, services/config/channel_config_service.py):
``get_all_channels`` walks ``config/channels/*.json`` and builds a dict. A file
that cannot be read is logged and **skipped**, and the function returns what it
managed to collect. The caller cannot tell a short result from a complete one.

What that costs is the channel's permissions. On a two-channel install, one
unreadable file means DDC comes up believing there is one channel: no status
messages are posted in the other one, and a command used there is refused with
"not allowed in this channel". The operator changed nothing and sees no reason.

The fallback in ``config_loader_service`` does not help, and cannot: it only
fires when the result is **completely** empty
(``if not channel_data.get('channel_permissions')``). A partial loss passes
straight through.

**A root-owned file is not hypothetical on this installation** - it is the same
cause as review E21, and the reason every ``docker exec`` here runs ``-u ddc``.

What is NOT done here, deliberately: the read failures are not plumbed into
``config_read_errors``. That key exists (``config_service.py:347``) and it is
consumed by ``app/auth.py:185`` to decide whether the login may fall back to
admin/setup. A corrupt channel file has nothing to do with the Web UI password
and must not touch who may log in.

So the repair is the one that fits: the loss is stated once, with its
consequence, in the place the operator looks - and it says what to do.
"""

import json
import logging

import pytest

VALID_A = "1283494245235294258"
VALID_B = "1360187769682657293"


@pytest.fixture
def service(tmp_path):
    from services.config.channel_config_service import ChannelConfigService

    instance = ChannelConfigService.__new__(ChannelConfigService)
    instance.channels_dir = tmp_path / "channels"
    instance.channels_dir.mkdir()
    instance.base_dir = tmp_path
    instance.main_config_file = tmp_path / "config.json"
    return instance


def _write(service, channel_id, payload):
    (service.channels_dir / f"{channel_id}.json").write_text(json.dumps(payload))


def test_the_readable_channels_still_come_back(service, caplog):
    _write(service, VALID_A, {"name": "tech", "commands": {"serverstatus": True}})
    (service.channels_dir / f"{VALID_B}.json").write_text("{ this is not json")

    with caplog.at_level(logging.DEBUG):
        channels = service.get_all_channels()

    assert VALID_A in channels, "a readable channel was lost along with the broken one"


def test_the_loss_is_stated_with_its_consequence(service, caplog):
    _write(service, VALID_A, {"name": "tech", "commands": {"serverstatus": True}})
    (service.channels_dir / f"{VALID_B}.json").write_text("{ this is not json")

    with caplog.at_level(logging.DEBUG):
        service.get_all_channels()

    errors = " ".join(r.getMessage() for r in caplog.records
                      if r.levelno >= logging.ERROR)
    assert errors, "nothing was logged at ERROR at all"
    assert "1 of 2" in errors or ("1" in errors and "2" in errors), (
        f"the operator is not told how many channels they lost: {errors!r}"
    )
    assert "permission" in errors.lower(), (
        f"the CONSEQUENCE is not named - a file error means those channels have "
        f"no permissions this run, and that is the part worth saying: {errors!r}"
    )


def test_a_clean_directory_says_nothing_alarming(service, caplog):
    """Counter-check: the normal case must not produce an error."""
    _write(service, VALID_A, {"name": "tech", "commands": {"serverstatus": True}})
    _write(service, VALID_B, {"name": "control", "commands": {"control": True}})

    with caplog.at_level(logging.DEBUG):
        channels = service.get_all_channels()

    assert len(channels) == 2
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "two perfectly good channel files produced an error"
    )


def test_an_empty_directory_is_not_an_error(service, caplog):
    """Counter-check: no channels configured is a state, not a failure."""
    with caplog.at_level(logging.DEBUG):
        channels = service.get_all_channels()

    assert channels == {}
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

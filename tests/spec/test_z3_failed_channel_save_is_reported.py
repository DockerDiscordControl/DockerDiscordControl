# -*- coding: utf-8 -*-
# @covers Z3
"""Z3 - if the channel permissions could not be saved, the panel says so.

THE FINDING (stage 4 review, stage B, section 11 F5, re-checked 2026-09-20):
``process_config_form`` calls ``_save_channel_permissions`` and never looks
at the outcome. That helper writes the channel files through
ChannelConfigService, logs an ERROR when the service returns False and
swallows every exception. The form answer came from the MAIN configuration
save alone, so the operator was told "Configuration saved" while the channel
permissions on disk were unchanged - the panel showed the new rights, the
bot kept the old ones.
"""

from unittest.mock import MagicMock

import pytest

from services.config.config_form_parser_service import ConfigFormParserService

CHANNEL = "123456789012345678"


def _form():
    return {"status_channel_id_1": CHANNEL, "status_channel_name_1": "status",
            "channel_tables_submitted": "1"}


@pytest.fixture
def config_service():
    service = MagicMock()
    service.save_config_service.return_value = MagicMock(success=True, error=None)
    return service


def _run(monkeypatch, channel_save_ok, config_service):
    channel_service = MagicMock()
    channel_service.save_all_channels.return_value = channel_save_ok
    monkeypatch.setattr("services.config.channel_config_service.get_channel_config_service",
                        lambda: channel_service)
    return ConfigFormParserService.process_config_form(_form(), {"channel_permissions": {}},
                                                       config_service)


def test_a_failed_channel_save_is_not_a_success(monkeypatch, config_service):
    _config, success, message = _run(monkeypatch, False, config_service)

    assert not success, (
        f"the channel permissions were not written, and the panel reports success: {message!r}"
    )
    assert "channel" in message.lower(), message


def test_a_working_save_is_still_a_success(monkeypatch, config_service):
    """Counter-check: otherwise 'never a success' would pass the test above."""
    _config, success, _message = _run(monkeypatch, True, config_service)

    assert success

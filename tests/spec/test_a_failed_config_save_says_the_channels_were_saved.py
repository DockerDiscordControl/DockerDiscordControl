# -*- coding: utf-8 -*-
"""A configuration save that fails after the channel permissions were written says so.

THE FINDING (stage 4 review before v3.1.0, section 12 pass 4 F13): the
channel permission files are written (and dropped ones removed) BEFORE
config.json. When that last write then failed (config/ unwritable, a full
disk), the panel said only "Configuration save failed ..." - although the
channel permissions had already changed and take effect at the next reload.

THE CONTRACT: the failure message says the channel permissions WERE saved.

HOW THIS TEST CAN FAIL: the message is silent about them again.

COUNTER-CHECK (2026-09-29): red before the change.
"""

from services.config.config_form_parser_service import ConfigFormParserService
from services.exceptions import ConfigSaveError


class _FailingSave:
    def get_config(self, force_reload=False):
        return {}

    def save_config(self, config):
        raise ConfigSaveError("config.json could not be written", error_code="CONFIG_SAVE_ERROR")


def test_the_message_names_the_channels_that_were_written(monkeypatch):
    written = []
    monkeypatch.setattr(ConfigFormParserService, "_save_channel_permissions",
                        staticmethod(lambda permissions: written.append(permissions) or True))
    form = {"channel_tables_submitted": "1",
            "status_channel_id_1": "123456789012345678", "status_channel_name_1": "status"}

    _config, ok, message = ConfigFormParserService.process_config_form(form, {}, _FailingSave())

    assert written and not ok
    assert "channel permissions" in message.lower() and "were saved" in message.lower(), message

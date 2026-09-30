# -*- coding: utf-8 -*-
"""A configuration save that fails after the password change says the password changed.

THE FINDING (stage 4 review before v3.1.0, section 12 pass 4 F4): the Web UI
password is changed first, before anything else of the form is written.
When a later step failed - a channel interval of "1.5" (the field allows it,
int() does not), config.json not writable, the channel files - the answer
said only what failed. The operator read "save failed", believed nothing
had changed, and could not log in with the old password afterwards.

THE CONTRACT: every failure after the password change says it changed.

HOW THIS TEST CAN FAIL: a failure message is silent about the password again.

COUNTER-CHECK (2026-09-30): red before the change, both cases.
"""

import pytest

from services.config.config_form_parser_service import ConfigFormParserService
from services.exceptions import ConfigSaveError


class _Config:
    def __init__(self, fail_save=False):
        self.fail_save = fail_save

    def get_config(self, force_reload=False):
        return {}

    def save_config(self, config):
        if self.fail_save:
            raise ConfigSaveError("config.json could not be written", error_code="CONFIG_SAVE_ERROR")
        raise AssertionError("not reached in these cases")


BASE = {"new_web_ui_password": "NewPass123!", "confirm_web_ui_password": "NewPass123!"}


@pytest.mark.parametrize("form,config", [
    (dict(BASE, channel_tables_submitted="1", status_channel_id_1="123456789012345678",
          status_channel_name_1="s", status_update_interval_minutes_1="1.5"), _Config()),
    (dict(BASE), _Config(fail_save=True)),
])
def test_the_failure_names_the_changed_password(monkeypatch, form, config):
    monkeypatch.setattr("services.config.config_service.change_web_ui_password", lambda password: None)
    monkeypatch.setattr(ConfigFormParserService, "_save_channel_permissions",
                        staticmethod(lambda permissions: True))

    _updated, ok, message = ConfigFormParserService.process_config_form(form, {}, config)

    assert not ok
    assert "password changed" in message.lower(), message

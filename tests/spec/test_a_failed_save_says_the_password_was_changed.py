# -*- coding: utf-8 -*-
"""A configuration save that fails after the password change says the password changed.

THE FINDING (stage 4 review before v3.1.0, section 12 pass 4 F4): the Web UI
password is changed first, before anything else of the form is written.
When a later step failed - config.json not writable, the channel files (a
channel interval of "1.5" was a third until it was read as 1, section 12
F10) - the answer
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


class _Saves(_Config):
    def save_config(self, config):
        from types import SimpleNamespace
        return SimpleNamespace(success=True, message="saved")


CHANNEL_FORM = dict(BASE, channel_tables_submitted="1", status_channel_id_1="123456789012345678",
                    status_channel_name_1="s")


@pytest.mark.parametrize("form,config,channels_written", [
    (CHANNEL_FORM, _Saves(), False),              # the channel files could not be written
    (dict(BASE), _Config(fail_save=True), True),  # config.json could not be written
])
def test_the_failure_names_the_changed_password(monkeypatch, form, config, channels_written):
    monkeypatch.setattr("services.config.config_service.change_web_ui_password", lambda password: None)
    monkeypatch.setattr(ConfigFormParserService, "_save_channel_permissions",
                        staticmethod(lambda permissions: channels_written))

    _updated, ok, message = ConfigFormParserService.process_config_form(form, {}, config)

    assert not ok
    assert "password changed" in message.lower(), message

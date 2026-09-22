# -*- coding: utf-8 -*-
"""A mistyped channel ID is said out loud, not answered with a deleted file.

THE FINDING: a channel ID that is not 17 to 19 digits is skipped with a log
line, and the parsed set of IDs is then handed to save_all_channels, which
removes every <channel_id>.json that is not in it. So dropping one digit
while editing a row - the most ordinary typing mistake there is - deletes
that channel's permission file, the bot stops answering there, and the panel
says "Configuration saved successfully". The duplicate-ID case is surfaced in
the answer; this one was not.

The IDs that were skipped are now named in the answer, the way duplicates
are.

COUNTER-CHECK (2026-09-22): red before - the save said nothing about the
skipped row. A valid list must stay silent (second test).
"""

import pytest

from services.config.config_form_parser_service import ConfigFormParserService

VALID = "123456789012345678"
SHORT = "1234567890123456"     # one digit missing
LETTERS = "12345678901234567x"


def _form(**ids):
    form = {}
    for index, (prefix, value) in enumerate(ids.items(), start=1):
        kind = "status" if prefix.startswith("status") else "control"
        form[f"{kind}_channel_id_{index}"] = value
    return form


def test_a_short_id_is_reported():
    skipped = ConfigFormParserService.find_unusable_channel_ids(
        {"status_channel_id_1": VALID, "status_channel_id_2": SHORT})

    assert skipped == [SHORT]


def test_letters_are_reported_too():
    skipped = ConfigFormParserService.find_unusable_channel_ids(
        {"control_channel_id_1": LETTERS})

    assert skipped == [LETTERS]


def test_a_valid_list_reports_nothing():
    """Counter-check: an ordinary save must not start warning."""
    assert ConfigFormParserService.find_unusable_channel_ids(
        {"status_channel_id_1": VALID, "control_channel_id_2": "876543210987654321"}) == []


def test_an_empty_row_is_not_a_mistake():
    """Counter-check: the tables always carry empty rows."""
    assert ConfigFormParserService.find_unusable_channel_ids(
        {"status_channel_id_1": "", "status_channel_id_2": "   "}) == []


def test_the_save_says_it(monkeypatch, tmp_path):
    """The answer the operator reads names the row that was not saved."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    from services.config import config_form_parser_service as parser

    class _Service:
        def get_config(self, force_reload=False):
            return {"channel_permissions": {}}

        def save_config(self, config):
            return type("R", (), {"success": True, "message": "Configuration saved"})()

    monkeypatch.setattr(parser.ConfigFormParserService, "_save_channel_permissions",
                        staticmethod(lambda *a, **kw: True))

    _config, success, message = parser.ConfigFormParserService.process_config_form(
        {"status_channel_id_1": VALID, "status_channel_id_2": SHORT},
        {"channel_permissions": {}}, _Service())

    assert success is True
    assert SHORT in message, message

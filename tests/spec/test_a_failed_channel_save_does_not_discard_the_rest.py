# -*- coding: utf-8 -*-
"""A channel-permission write that fails does not discard the container edits.

THE FINDING (independent review of the web panel, 2026-09-23): one Save in the
panel writes several things - config.json, the channel permission files, the
server order, the container configs and the container info. They are written in
that order, and the channel permissions are written BEFORE config.json.

When the channel files cannot be written - the classic case this codebase keeps
citing, a config/channels/ left behind root-owned by a `docker exec` without
`-u ddc` - process_config_form has already written config.json and then reports
the save as failed. ConfigurationSaveService sees that and returns at once, so
steps 5 and 6 never run: the server order, the container configs and the
container info are NOT written at all.

What the operator gets is one sentence about channel permissions. What actually
happened is that their main settings WERE saved, their container settings were
NOT, and nothing says so. Pressing Save again changes nothing until the
permissions are fixed, and meanwhile config.json and the container files
disagree about what was just saved.

The save still fails - the channel permissions really did not get written, and
SPEC.md Z3 says no success is reported that did not happen. What changes is
that everything that CAN be written is written first, and the message names
both halves.

HOW THIS TEST CAN FAIL: it makes the channel write fail and then asks whether
the container files were written. If they were not, the test is red.

COUNTER-CHECK (2026-09-23): red before - the container files were never
written. The other tests hold the rest still: a failure for any other reason
still stops before anything else is written, and the ordinary save is
unchanged.
"""

from unittest.mock import patch

import pytest

from services.config.config_form_parser_service import CHANNELS_NOT_SAVED_MESSAGE
from services.web.configuration_save_service import (ConfigurationSaveService,
                                                     ConfigurationSaveRequest)


class _Recorder:
    """A save service whose disk steps only record that they were reached."""

    def __init__(self, process_result):
        self.service = ConfigurationSaveService()
        self.order_saved = []
        self.files_saved = []
        self._process_result = process_result

        self.service._initialize_dependencies = lambda: _ok()
        self.service._process_configuration = lambda form: self._process_result
        self.service._save_server_order = lambda data: self.order_saved.append(data)
        self.service._save_configuration_files = lambda data, form, split: (
            self.files_saved.append(data) or _files_ok())
        self.service._handle_critical_changes = lambda changes: None
        self.service._update_logging_settings = lambda: None
        self.service._log_save_action = lambda: None

    def run(self):
        request = ConfigurationSaveRequest(form_data={"servers": "x"})
        with patch("services.config.config_service.load_config", return_value={}):
            return self.service.save_configuration(request)


def _ok():
    from services.web.configuration_save_service import ConfigurationSaveResult

    return ConfigurationSaveResult(success=True)


def _files_ok():
    from services.web.configuration_save_service import SaveFilesResult

    return SaveFilesResult(success=True, config_files=["config.json"])


CONFIG = {"servers": [{"docker_name": "nginx"}]}


def test_the_container_edits_are_still_written():
    """THE FINDING: they were dropped along with the channel failure."""
    recorder = _Recorder((CONFIG, False, CHANNELS_NOT_SAVED_MESSAGE))

    result = recorder.run()

    assert recorder.files_saved == [CONFIG], (
        "the operator's container settings were never written - only the "
        "channel permissions had failed")
    assert recorder.order_saved == [CONFIG], "the server order was never written"
    assert result.success is False, "the channel permissions really did fail"
    assert "channel" in (result.message or result.error or "").lower()


def test_the_message_says_what_was_saved_and_what_was_not():
    """One sentence about channels left the operator guessing about the rest."""
    recorder = _Recorder((CONFIG, False, CHANNELS_NOT_SAVED_MESSAGE))

    result = recorder.run()
    text = (result.message or result.error or "").lower()

    assert "channel" in text
    assert "container" in text or "rest" in text or "other" in text, (
        f"the message does not say what WAS saved: {text!r}")


def test_a_failure_for_any_other_reason_still_stops_at_once():
    """Counter-check: a half-processed configuration is not written to disk."""
    recorder = _Recorder(({}, False, "Data error processing configuration: boom"))

    result = recorder.run()

    assert recorder.files_saved == [], "a failed processing wrote container files anyway"
    assert recorder.order_saved == [], "a failed processing wrote the server order anyway"
    assert result.success is False


def test_the_ordinary_save_is_unchanged():
    """Counter-check: nothing about the everyday path moved."""
    recorder = _Recorder((CONFIG, True, "Configuration saved"))

    result = recorder.run()

    assert result.success is True
    assert recorder.files_saved == [CONFIG]
    assert recorder.order_saved == [CONFIG]


def test_the_parser_really_returns_that_message():
    """The two sides share one constant, so this comparison cannot drift."""
    import services.config.config_form_parser_service as parser

    source = open(parser.__file__, encoding="utf-8").read()
    assert "return updated_config, False, CHANNELS_NOT_SAVED_MESSAGE" in source, (
        "process_config_form no longer returns the shared constant, so "
        "ConfigurationSaveService can no longer tell this failure from any other")

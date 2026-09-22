# -*- coding: utf-8 -*-
"""A failed write to the action log says so where the operator looks.

THE FINDING: log_user_action and get_action_logs_text reported a failure with
print(..., file=sys.stderr). The action log is the record of who started,
stopped or restarted what; when writing it fails, that line is the only trace
that an action went unrecorded - and stderr is not where DDC's log lives. The
panel shows the application log, and under supervisord stderr goes somewhere
else entirely. SPEC.md Z8 counts that as silent.

Both now go through logger.error, like the sibling get_action_logs_json, which
was moved off stderr for the same reason (review D5).

COUNTER-CHECK (2026-09-23): red before - no ERROR record on the logger, the
text sat in capsys instead. test_a_write_that_worked_says_nothing holds the
other side: logging an error unconditionally would be green without it.
"""

import logging
from types import SimpleNamespace

import pytest

from services.infrastructure import action_logger


@pytest.fixture
def failing_service(monkeypatch):
    service = SimpleNamespace(
        log_action=lambda *a, **k: SimpleNamespace(
            success=False, error="action log not writable", data=None),
        get_logs=lambda **k: SimpleNamespace(
            success=False, error="action log not readable", data=None))
    monkeypatch.setattr(action_logger, "get_action_log_service", lambda: service)
    return service


@pytest.fixture
def working_service(monkeypatch):
    service = SimpleNamespace(
        log_action=lambda *a, **k: SimpleNamespace(success=True, error=None, data=None),
        get_logs=lambda **k: SimpleNamespace(success=True, error=None, data="a line"))
    monkeypatch.setattr(action_logger, "get_action_log_service", lambda: service)
    return service


def _errors(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_failed_write_is_an_error_in_the_log(failing_service, caplog):
    with caplog.at_level(logging.DEBUG):
        action_logger.log_user_action("STOP", "nginx", user="admin", source="Web UI")

    assert any("action log not writable" in message for message in _errors(caplog)), (
        "an action went unrecorded and the only trace was on stderr")


def test_a_failed_read_is_an_error_in_the_log(failing_service, caplog):
    with caplog.at_level(logging.DEBUG):
        text = action_logger.get_action_logs_text()

    assert "Error loading action logs" in text     # what the caller still shows
    assert any("action log not readable" in message for message in _errors(caplog))


def test_a_write_that_worked_says_nothing(working_service, caplog):
    """Counter-check: the everyday case must stay quiet."""
    with caplog.at_level(logging.DEBUG):
        action_logger.log_user_action("START", "nginx", user="admin", source="Web UI")

    assert _errors(caplog) == []


def test_a_read_that_worked_returns_the_text(working_service, caplog):
    """Counter-check: the everyday case, again."""
    with caplog.at_level(logging.DEBUG):
        assert action_logger.get_action_logs_text() == "a line"

    assert _errors(caplog) == []

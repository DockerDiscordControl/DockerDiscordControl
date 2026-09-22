# -*- coding: utf-8 -*-
"""An action log that could not be read is not an action log with no entries.

THE FINDING (review D5, pass 2, section 18 F3): `get_action_logs_json`
answers `[]` when the service reports a failure - an unreadable or corrupted
user_actions.json, an IOError during the read - and `[]` is exactly what it
answers when there genuinely are no entries. Its sibling
`get_action_logs_text` returns an error string on the same failure, so the
two disagree about what a failure looks like.

`ContainerLogService._get_action_logs_json` then wraps that empty list in
`success=True, count=0`, and the panel shows a clean, empty history. The
route right behind it knows how to report a failure and never gets one.

The failure also only reached `print(..., file=sys.stderr)` - not the log the
operator reads.
"""

import logging

import pytest

from services.infrastructure import action_logger
from services.web.container_log_service import ActionLogRequest, get_container_log_service

# The promise is "it raises instead of answering an empty list", not a
# particular class name - naming a class the code does not have yet would make
# this file fail to collect rather than fail for the finding.
RAISES = RuntimeError


class _Result:
    def __init__(self, success, data=None, error=None):
        self.success = success
        self.data = data or []
        self.error = error


class _Entry:
    def __init__(self, action):
        self.action = action

    def to_dict(self):
        return {"action": self.action}


@pytest.fixture
def service(monkeypatch):
    """The action log service, answering whatever the test asks it to."""
    def _answer(result):
        monkeypatch.setattr(action_logger, "get_action_log_service",
                            lambda: type("S", (), {
                                "get_logs": staticmethod(lambda **kwargs: result)})())
    return _answer


def test_an_unreadable_log_is_not_an_empty_list(service):
    service(_Result(False, error="user_actions.json is corrupted"))

    with pytest.raises(RAISES):
        action_logger.get_action_logs_json(limit=10)


def test_the_panel_is_told_it_failed(service):
    service(_Result(False, error="user_actions.json is corrupted"))

    result = get_container_log_service().get_action_logs(
        ActionLogRequest(format_type="json", limit=10))

    assert result.success is False, (
        "a log that could not be read was shown to the operator as a clean, empty history"
    )


def test_the_failure_reaches_the_log(service, caplog):
    service(_Result(False, error="user_actions.json is corrupted"))

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(RAISES):
            action_logger.get_action_logs_json(limit=10)

    assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "the reason went to stderr, not to the log the operator reads"
    )


def test_a_log_with_no_entries_is_still_empty(service):
    """Counter-check: genuinely empty must stay a clean, successful empty."""
    service(_Result(True, data=[]))

    assert action_logger.get_action_logs_json(limit=10) == []

    result = get_container_log_service().get_action_logs(
        ActionLogRequest(format_type="json", limit=10))
    assert result.success is True
    assert result.data["count"] == 0


def test_entries_still_come_through(service):
    """Counter-check: refusing everything would pass the tests above."""
    service(_Result(True, data=[_Entry("START"), _Entry("STOP")]))

    assert action_logger.get_action_logs_json(limit=10) == [
        {"action": "START"}, {"action": "STOP"}]

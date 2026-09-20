# -*- coding: utf-8 -*-
"""
THE FINDING (review C23, section 29 F2): `_get_action_logs_text` and
`_get_action_logs_json` catch

    except (ImportError, AttributeError, OSError, TypeError[, ValueError]) as e:
        self.logger.error(...)
        raise

- they log and re-raise on purpose, leaving the answer to their caller. But the
caller, `get_action_logs`, catches only

    except (AttributeError, TypeError, ValueError, RuntimeError) as e:

`ImportError` and `OSError` are in the first list and missing from the second.
So exactly the two failures the helpers were written to hand upwards - the
action_logger module not importable, or its file unreadable - leave the service
uncaught instead of becoming the intended
`LogResult(success=False, ..., status_code=500)`. The web panel gets an
unhandled exception where the code is visibly trying to produce a polite error.

An except clause that is meant to catch what its callees re-raise has to be a
superset of it. This one was not.

The counter-check (test_a_working_log_still_comes_back) keeps the ordinary path
intact.
"""

import sys
import types

import pytest

from services.web.container_log_service import ActionLogRequest, ContainerLogService


@pytest.fixture
def service():
    return ContainerLogService()


def _action_logger(monkeypatch, text_error=None, content="a log line"):
    module = types.ModuleType("services.infrastructure.action_logger")

    def _text(limit):
        if text_error:
            raise text_error
        return content

    def _json(limit):
        if text_error:
            raise text_error
        return [{"action": "START"}]

    module.get_action_logs_text = _text
    module.get_action_logs_json = _json
    monkeypatch.setitem(sys.modules, "services.infrastructure.action_logger", module)


def test_an_unreadable_log_file_becomes_an_answer(service, monkeypatch):
    """THE FINDING: OSError is re-raised by the helper and not caught above."""
    _action_logger(monkeypatch, text_error=OSError("action log unreadable"))

    result = service.get_action_logs(ActionLogRequest(format_type="text"))

    assert result.success is False
    assert result.status_code == 500


def test_a_missing_action_logger_becomes_an_answer(service, monkeypatch):
    """The other half: ImportError, the case the helper names first."""
    monkeypatch.setitem(sys.modules, "services.infrastructure.action_logger", None)

    result = service.get_action_logs(ActionLogRequest(format_type="json"))

    assert result.success is False
    assert result.status_code == 500


def test_a_working_log_still_comes_back(service, monkeypatch):
    """COUNTER-CHECK: the ordinary path is untouched."""
    _action_logger(monkeypatch, content="2026-09-20 START container=web")

    result = service.get_action_logs(ActionLogRequest(format_type="text"))

    assert result.success is True
    assert "START" in result.content

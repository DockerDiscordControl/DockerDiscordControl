# -*- coding: utf-8 -*-
"""The action-log download serves the file the action log is written to.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review pass 1, section 18 F4, re-checked 2026-09-19 on
the operator's server): the web panel's "download action log" button and the
``/action-log`` endpoint read ``ACTION_LOG_FILE`` from
services/infrastructure/action_logger.py - ``logs/action_log.json``. The log
is written by ActionLogService to ``logs/user_actions.log`` (and .json). On
the server only ``user_actions.*`` existed, so the button answered "Action
log file not found". Three places named this file (action_logger,
app/utils/web_helpers.py, the service itself), and one had drifted.

HOW IT IS CHECKED: every exported path is compared with what the service
really writes - its ``text_log_file`` - not with a restated formula.
"""

from pathlib import Path

import pytest

from services.infrastructure.action_log_service import ActionLogService


def _written():
    return Path(ActionLogService().text_log_file).resolve()


def _routes_file():
    from app.blueprints import action_log_routes
    return action_log_routes.ACTION_LOG_FILE


def _logger_file():
    from services.infrastructure import action_logger
    return action_logger.ACTION_LOG_FILE


def _helpers_file():
    from app.utils import web_helpers
    return web_helpers.ACTION_LOG_FILE


@pytest.mark.parametrize("source", [_routes_file, _logger_file, _helpers_file],
                         ids=["action_log_routes", "action_logger", "web_helpers"])
def test_every_exported_path_is_the_written_file(source):
    assert Path(source()).resolve() == _written(), (
        f"{source.__name__[1:]} points to {source()} but the action log is written to "
        f"{_written()} - the download finds nothing"
    )

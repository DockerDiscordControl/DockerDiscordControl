# -*- coding: utf-8 -*-
"""The health check is logged when it fails, not when it passes.

MY OWN REGRESSION, found while answering the operator's "does every message
make sense now?". His log carries this every thirty seconds:

    127.0.0.1 - - [25/Sep/2026 10:28:58] "GET /health HTTP/1.1" 200 -

29 of them in 25 minutes, about 2,880 a day. They are new since yesterday and
they are mine. Self-signed TLS cannot be served by waitress, so the panel now
runs on werkzeug's threaded server - and werkzeug logs an access line for every
request while waitress logs none. The Dockerfile's HEALTHCHECK polls every 30s
(--interval=30s), so switching the server on quietly switched this on with it.

THE RULE, and it is why this is a filter and not a silencing: a health check
that PASSES says nothing that was not already true. A health check that FAILS
is the single most important line in the file - it is the moment Docker is
about to restart the container, and an operator reading backwards needs to see
it. So 2xx on /health is dropped and everything else is kept: a 500, a 503, a
request to any other path, and everything at all in debug mode.

WHAT THIS IS NOT: turning off the access log. Somebody reaching the panel is
worth a line; it is the automated poll talking to itself that is not.

HOW THIS TEST CAN FAIL: a failing health check going quiet, an ordinary
request being swallowed, or the filter not reaching the logger that writes
these lines.

COUNTER-CHECK (2026-09-25): red before - no such filter existed, and the case
that feeds it a passing check saw the line survive.
"""

import importlib.util
import logging
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]


def _the_module():
    """Loaded straight from the file, not through `app.web`.

    Importing the package drags in app_factory, which uses dataclass(slots=),
    so `from app.web.logging import ...` is a Python 3.10 requirement - this
    file would then only ever run inside the container and never while the
    change is being made. The module itself needs nothing but logging and re.
    """
    spec = importlib.util.spec_from_file_location(
        "ddc_web_logging_under_test", PROJECT / "app" / "web" / "logging.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HealthCheckLogFilter = _the_module().HealthCheckLogFilter

PASSING = '127.0.0.1 - - [25/Sep/2026 10:28:58] "GET /health HTTP/1.1" 200 -'
FAILING = '127.0.0.1 - - [25/Sep/2026 10:28:58] "GET /health HTTP/1.1" 503 -'
CRASHED = '127.0.0.1 - - [25/Sep/2026 10:28:58] "GET /health HTTP/1.1" 500 -'
A_PERSON = '192.168.1.50 - - [25/Sep/2026 10:28:58] "GET /settings HTTP/1.1" 200 -'


def _record(message):
    return logging.LogRecord("werkzeug", logging.INFO, __file__, 1, message, (), None)


def _kept(message, debug_mode=False):
    return HealthCheckLogFilter(debug_mode=debug_mode).filter(_record(message))


def test_a_passing_health_check_is_dropped():
    """THE FINDING: 2,880 identical lines a day, all of them saying nothing."""

    assert _kept(PASSING) is False


@pytest.mark.parametrize("line", [FAILING, CRASHED])
def test_a_failing_health_check_is_kept(line):
    """THE CASE THAT MATTERS. This is the moment before Docker restarts the
    container. Dropping it to save noise would trade the whole point of the
    check for a quieter file."""

    assert _kept(line) is True, line


def test_somebody_reaching_the_panel_is_still_logged():
    """Counter-check: silencing werkzeug altogether would pass the first case
    and lose every access line with it."""

    assert _kept(A_PERSON) is True


def test_debug_mode_keeps_everything():
    """An operator who turned debug on is asking to see the plumbing, and the
    poll is plumbing."""

    assert _kept(PASSING, debug_mode=True) is True


def test_a_health_check_that_is_not_a_get_is_kept():
    """Only the automated poll is uninteresting, and the poll is a GET. A POST
    to /health is somebody or something else, and worth a line."""

    assert _kept('1.2.3.4 - - [x] "POST /health HTTP/1.1" 200 -') is True


def test_another_path_that_merely_starts_the_same_is_kept():
    """/healthcheck-report or /health-history are not the poll. Matching on a
    prefix would swallow them."""

    assert _kept('1.2.3.4 - - [x] "GET /health-history HTTP/1.1" 200 -') is True


def test_the_filter_reaches_the_logger_that_writes_these_lines():
    """The decision above is worth nothing if it is installed somewhere else.
    werkzeug's access lines go to the logger named "werkzeug".

    RUN, NOT READ. The first version of this case searched configure_logging's
    source for the words "HealthCheckLogFilter" and "werkzeug". Deleting the
    single addFilter line left it GREEN - the filter was still constructed, so
    the name was still there, and the panel would have logged every health
    check exactly as before. That is the sixth sabotage to survive one of my
    own cases by keeping a name the case was searching for. So this one calls
    configure_logging and asks the werkzeug logger what it ended up with.
    """
    module = _the_module()
    werkzeug_logger = logging.getLogger("werkzeug")
    before = list(werkzeug_logger.filters)

    class _Stub:
        config = {"LOG_LEVEL": "INFO"}
        logger = logging.getLogger("ddc_health_filter_stub")

    try:
        module.configure_logging(_Stub())
        installed = [f for f in werkzeug_logger.filters
                     if isinstance(f, module.HealthCheckLogFilter)]

        assert installed, ("nothing attaches the filter to werkzeug's logger, so "
                           "every health check is still logged")
        # And it must actually be doing its job there, not merely present.
        # Truthiness, not identity: since Python 3.12 Logger.filter() returns
        # the RECORD rather than True, so `is True` passed on the Mac's 3.9 and
        # failed inside the production image - which is the runtime that counts.
        assert not werkzeug_logger.filter(_record(PASSING))
        assert werkzeug_logger.filter(_record(FAILING))
    finally:
        for leftover in list(werkzeug_logger.filters):
            if leftover not in before:
                werkzeug_logger.removeFilter(leftover)
        for name in ("", "gunicorn.access", "gunicorn.error", "flask.app",
                     "app.blueprints.main_routes", "__main__"):
            other = logging.getLogger(name)
            for leftover in list(other.filters):
                if isinstance(leftover, (module.HealthCheckLogFilter,
                                         module.ConsumePowerLogFilter)):
                    other.removeFilter(leftover)

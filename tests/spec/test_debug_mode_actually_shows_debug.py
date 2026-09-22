# -*- coding: utf-8 -*-
"""
THE FINDING (review C9, section 36 F1): `enable_temporary_debug()` announces

    **** Debug mode will now show detailed logs until it expires ****

and then carefully swaps every handler's `DebugModeFilter` for a fresh one -
but touches no level anywhere. The loggers `setup_logger()` built are at
`level` (INFO at startup, via `setup_all_loggers`), and so are their handlers.
Python drops a DEBUG record twice before any filter is consulted:
`Logger.debug` returns immediately unless `isEnabledFor(DEBUG)`, and
`callHandlers` compares `record.levelno >= hdlr.level`. `DebugModeFilter` -
the thing the function does refresh - only ever runs for records that got that
far. So for every logger that existed before debug mode was switched on, the
promised detailed logs never appear. Nothing errors; the operator turns debug
on, sees nothing, and has no way to tell that the switch did nothing.

The switch is meant to be the filter's job: `DebugModeFilter.filter` lets DEBUG
through exactly while debug mode is on and passes INFO and above regardless. It
can only do that job if the levels let the record reach it.

The counter-check (test_debug_off_still_suppresses_debug) holds the other end:
raising the levels must not turn the debug switch into "DEBUG always on".
"""

import logging

import pytest

from utils import logging_utils


@pytest.fixture
def debug_state():
    """Debug mode is module-global state - put it back exactly as found."""
    saved = (
        logging_utils._temp_debug_mode_enabled,
        logging_utils._temp_debug_expiry,
        logging_utils._debug_mode_enabled,
    )
    yield
    (logging_utils._temp_debug_mode_enabled,
     logging_utils._temp_debug_expiry,
     logging_utils._debug_mode_enabled) = saved


@pytest.fixture
def logger_at_info(debug_state):
    """A logger as the application builds it at startup: INFO, console handler,
    DebugModeFilter attached. Removed again afterwards so the global logging
    tree is left as it was."""
    name = "ddc.spec.c9"
    logger = logging_utils.setup_logger(name, level=logging.INFO)
    records = []

    class _Collect(logging.Handler):
        def emit(self, record):
            records.append(record)

    collector = _Collect()
    collector.setLevel(logging.INFO)
    collector.addFilter(logging_utils.DebugModeFilter())
    logger.addHandler(collector)

    yield logger, records

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.setLevel(logging.NOTSET)
    logging.root.manager.loggerDict.pop(name, None)


def test_the_switch_reaches_the_loggers_that_already_exist(logger_at_info):
    """THE FINDING: debug on must actually produce a DEBUG line."""
    logger, records = logger_at_info

    ok, _expiry = logging_utils.enable_temporary_debug(duration_minutes=5)
    assert ok is True
    logger.debug("the detailed line the operator was promised")

    assert [r.getMessage() for r in records] == [
        "the detailed line the operator was promised"]


def test_the_switch_reaches_the_handlers_too(logger_at_info):
    """Not only the logger's own level - a handler still at INFO drops the
    record before its filter is ever asked."""
    logger, _records = logger_at_info
    logging_utils.enable_temporary_debug(duration_minutes=5)

    assert logger.isEnabledFor(logging.DEBUG)
    assert all(h.level <= logging.DEBUG for h in logger.handlers)


def test_debug_off_still_suppresses_debug(logger_at_info):
    """COUNTER-CHECK: the switch must still be a switch. Turned off again, a
    DEBUG line must not appear - while INFO passes as it always did."""
    logger, records = logger_at_info

    logging_utils.enable_temporary_debug(duration_minutes=5)
    logging_utils.disable_temporary_debug()

    logger.debug("must not appear")
    logger.info("must appear")

    assert [r.getMessage() for r in records] == ["must appear"]


def test_a_logger_born_while_debug_is_on_also_shows_debug(debug_state):
    """The mirror image of the finding: the levels are set when a logger is
    BUILT, and most of DDC's loggers are built at import time - but not all of
    them. One created while debug mode is already running must not be deaf for
    the rest of the session."""
    logging_utils.enable_temporary_debug(duration_minutes=5)
    name = "ddc.spec.c9.born_later"
    logger = logging_utils.setup_logger(name, level=logging.INFO)
    records = []

    class _Collect(logging.Handler):
        def emit(self, record):
            records.append(record)

    collector = _Collect()
    collector.setLevel(logging.DEBUG)
    logger.addHandler(collector)
    try:
        logger.debug("the line the operator was promised")
        assert [r.getMessage() for r in records] == [
            "the line the operator was promised"]
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)
        logging.root.manager.loggerDict.pop(name, None)
        logging_utils.disable_temporary_debug()


def test_the_levels_go_back_where_they_were(debug_state):
    """A five-minute debug switch must not leave a deliberately configured
    level changed for the rest of the process.

    Noted honestly: the SUPPRESSION after switching off does not depend on
    this - DebugModeFilter blocks DEBUG on its own, which is why removing the
    restore leaves every other test in this file green. What it does depend on
    is this: a logger someone set to WARNING stays at WARNING afterwards.
    """
    name = "ddc.spec.c9.restore"
    logger = logging_utils.setup_logger(name, level=logging.WARNING)
    try:
        logging_utils.enable_temporary_debug(duration_minutes=5)
        assert logger.level == logging.DEBUG  # lowered while debug is on

        logging_utils.disable_temporary_debug()

        assert logger.level == logging.WARNING
        assert all(h.level == logging.WARNING for h in logger.handlers)
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)
        logging.root.manager.loggerDict.pop(name, None)
        logging_utils.disable_temporary_debug()

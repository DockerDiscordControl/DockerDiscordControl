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

RE-AIMED 2026-09-26, and the rule is untouched. Every case below used to drive
`enable_temporary_debug()`, and the temporary debug mode was removed that day:
its three controls left `_log_section.html` on 2025-08-12 and nothing has been
able to reach any layer of it since. The finding was never about that
mechanism - it is about `_apply_debug_levels`, which is what the PERMANENT
switch in the panel calls through `refresh_debug_status()` and what
`setup_logger` calls for a logger born while debug is already on. So the cases
drive that directly, which is also one indirection fewer between the case and
the thing it is about.
"""

import logging

import pytest

from utils import logging_utils


@pytest.fixture
def debug_state():
    """Debug mode is module-global state - put it back exactly as found."""
    saved_flag = logging_utils._debug_mode_enabled
    saved_check = logging_utils.is_debug_mode_enabled
    # THE SWITCH IS ASKED, NOT READ. DebugModeFilter calls
    # is_debug_mode_enabled(), and that function re-reads the configuration
    # and overwrites the module global - so setting the global alone does not
    # switch anything, and a first version of this fixture was red for that
    # reason. The panel's saved setting is what it would normally find; here
    # it finds _ASKED.
    logging_utils.is_debug_mode_enabled = lambda: _ASKED["on"]
    _ASKED["on"] = False
    yield
    logging_utils.is_debug_mode_enabled = saved_check
    logging_utils._debug_mode_enabled = saved_flag
    logging_utils._apply_debug_levels(False)


# What the stubbed is_debug_mode_enabled() answers, so a case can flip the
# switch in the middle of itself.
_ASKED = {"on": False}


def _switch_debug(on):
    """The panel's switch, as far as the logging tree is concerned.

    refresh_debug_status() re-reads the configuration and then calls exactly
    this pair; driving them here keeps the case about the levels rather than
    about the config service.
    """
    _ASKED["on"] = on
    logging_utils._apply_debug_levels(on)


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

    _switch_debug(True)
    logger.debug("the detailed line the operator was promised")

    assert [r.getMessage() for r in records] == [
        "the detailed line the operator was promised"]


def test_the_switch_reaches_the_handlers_too(logger_at_info):
    """Not only the logger's own level - a handler still at INFO drops the
    record before its filter is ever asked."""
    logger, _records = logger_at_info
    _switch_debug(True)

    assert logger.isEnabledFor(logging.DEBUG)
    assert all(h.level <= logging.DEBUG for h in logger.handlers)


def test_debug_off_still_suppresses_debug(logger_at_info):
    """COUNTER-CHECK: the switch must still be a switch. Turned off again, a
    DEBUG line must not appear - while INFO passes as it always did."""
    logger, records = logger_at_info

    _switch_debug(True)
    _switch_debug(False)

    logger.debug("must not appear")
    logger.info("must appear")

    assert [r.getMessage() for r in records] == ["must appear"]


def test_a_logger_born_while_debug_is_on_also_shows_debug(debug_state):
    """The mirror image of the finding: the levels are set when a logger is
    BUILT, and most of DDC's loggers are built at import time - but not all of
    them. One created while debug mode is already running must not be deaf for
    the rest of the session."""
    _switch_debug(True)
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
        _switch_debug(False)


def test_the_levels_go_back_where_they_were(debug_state):
    """The debug switch must not leave a deliberately configured level
    changed for the rest of the process.

    Noted honestly: the SUPPRESSION after switching off does not depend on
    this - DebugModeFilter blocks DEBUG on its own, which is why removing the
    restore leaves every other test in this file green. What it does depend on
    is this: a logger someone set to WARNING stays at WARNING afterwards.
    """
    name = "ddc.spec.c9.restore"
    logger = logging_utils.setup_logger(name, level=logging.WARNING)
    try:
        _switch_debug(True)
        assert logger.level == logging.DEBUG  # lowered while debug is on

        _switch_debug(False)

        assert logger.level == logging.WARNING
        assert all(h.level == logging.WARNING for h in logger.handlers)
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        logger.setLevel(logging.NOTSET)
        logging.root.manager.loggerDict.pop(name, None)
        _switch_debug(False)

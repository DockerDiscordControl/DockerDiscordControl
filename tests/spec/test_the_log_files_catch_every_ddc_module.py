# -*- coding: utf-8 -*-
"""discord.log and bot_error.log receive every DDC module, not just one.

THE OPERATOR (2026-09-25): "please go through the logs again (startup)."
Reading them turned up a line that announces something and is never answered:

    ddc.docker_control - INFO - Starting MechStatusCacheService background loop...

and then nothing. No "started successfully", no error - and the service's own
first line, "Starting mech status cache loop (interval: 30s...)", is not in the
log either.

THE FILES HOLD ONE LOGGER. Measured on his machine:

    discord.log        every line from ddc.bot, and nothing else
    services.* lines   zero, in the file and on the console

ensure_log_files attaches the two rotating handlers to the `ddc.bot` logger.
ddc.docker_control, ddc.status_handlers, ddc.scheduler and the rest are its
SIBLINGS, not its children: their records propagate to `ddc`, which has no
handler, and stop there. They reach the console because setup_logger gives
each one its own stream handler - which is why the gap is invisible until you
open the file.

WHY IT MATTERS TODAY IN PARTICULAR. An hour before this was found, the panel's
Application tab was pointed at bot_error.log precisely because it is the only
log that survives a rebuild. It does - and it has been collecting the errors of
exactly one logger out of twenty. An operator reading it after a crash in
ddc.docker_control would find nothing and conclude nothing had happened.

THE FIX IS WHERE THE HANDLERS HANG, not what the modules do. Attached to `ddc`,
every ddc.* logger's records pass through on their way up. The console handlers
stay where they are, on the individual loggers, so nothing is printed twice.

STILL OPEN, and not this commit: 32 files log to logging.getLogger(__name__),
so their names are services.*, utils.* and app.*. Those are not under `ddc` and
remain invisible - the mech cache service among them, which is how this started.

HOW THIS TEST CAN FAIL: a DDC module whose records cannot reach the files.

COUNTER-CHECK (2026-09-25): red before - a record on ddc.docker_control reached
no handler at all.
"""

import logging
from pathlib import Path

import pytest

from app.bootstrap.runtime import ensure_log_files

PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ddc_logger(tmp_path):
    """The `ddc` logger with the two files attached, and nothing left behind."""
    root = logging.getLogger("ddc")
    before = list(root.handlers)
    ensure_log_files(root, tmp_path)
    yield root, tmp_path
    for handler in list(root.handlers):
        if handler not in before:
            handler.close()
            root.removeHandler(handler)


def _files(directory):
    return {path.name for path in Path(directory).glob("*.log")}


def test_a_module_other_than_the_bot_reaches_the_files(ddc_logger):
    """THE FINDING: the files held ddc.bot alone, and bot_error.log is what the
    panel's Application tab shows."""
    _root, directory = ddc_logger
    logging.getLogger("ddc.docker_control").error("a container action failed")
    for handler in logging.getLogger("ddc").handlers:
        handler.flush()

    written = (Path(directory) / "bot_error.log").read_text(encoding="utf-8")

    assert "a container action failed" in written, written[:200]


def test_the_bot_itself_still_reaches_them(ddc_logger):
    """Counter-check: moving the handlers up must not drop what they already
    caught."""
    _root, directory = ddc_logger
    logging.getLogger("ddc.bot").error("the token could not be decrypted")
    for handler in logging.getLogger("ddc").handlers:
        handler.flush()

    written = (Path(directory) / "bot_error.log").read_text(encoding="utf-8")

    assert "the token could not be decrypted" in written


def test_the_everything_file_takes_info_too(ddc_logger):
    """The two files divide the work: one keeps everything, one keeps only
    failures. Both must still do their own job."""
    _root, directory = ddc_logger
    logging.getLogger("ddc.status_handlers").info("a status refresh finished")
    for handler in logging.getLogger("ddc").handlers:
        handler.flush()

    everything = (Path(directory) / "discord.log").read_text(encoding="utf-8")
    failures = (Path(directory) / "bot_error.log").read_text(encoding="utf-8")

    assert "a status refresh finished" in everything
    assert "a status refresh finished" not in failures, (
        "the failures file is collecting ordinary lines")


def test_both_files_are_created(ddc_logger):
    """Counter-check on the fixture itself: a case that wrote into nothing
    would pass the others by finding its own text in an empty string."""
    _root, directory = ddc_logger

    assert _files(directory) == {"discord.log", "bot_error.log"}, _files(directory)


def test_hanging_them_on_the_bot_alone_loses_the_rest(tmp_path):
    """THE DEFECT ITSELF, reproduced. The cases above describe the end state
    and would pass either way, because the fixture already attaches the
    handlers where they belong - so without this one the file would go green
    on a bug it never exercised.

    Attached to ddc.bot, as they were, a record from a SIBLING logger reaches
    nothing: it propagates to `ddc`, which has no handler, and stops.
    """
    bot = logging.getLogger("ddc.bot")
    before = list(bot.handlers)
    ensure_log_files(bot, tmp_path)
    try:
        logging.getLogger("ddc.docker_control").error("an error nobody would see")
        for handler in bot.handlers:
            handler.flush()
        written = (Path(tmp_path) / "bot_error.log").read_text(encoding="utf-8")
    finally:
        for handler in list(bot.handlers):
            if handler not in before:
                handler.close()
                bot.removeHandler(handler)

    assert "an error nobody would see" not in written, (
        "this is the arrangement that WORKED - then the finding was wrong")


def test_the_handlers_hang_on_the_family_not_on_one_member():
    """Read from the code: build_runtime must hand ensure_log_files the logger
    every DDC module passes through, not the bot's own."""
    import ast

    source = (PROJECT / "app" / "bot" / "runtime.py").read_text(encoding="utf-8")
    calls = [node for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call)
             and ast.unparse(node.func).endswith("ensure_log_files")]

    assert calls, "nothing attaches the log files any more"
    for call in calls:
        given = ast.unparse(call.args[0])

        assert "ddc" in given and "ddc.bot" not in given, (
            f"the files hang on {given}, so only that one logger reaches them")

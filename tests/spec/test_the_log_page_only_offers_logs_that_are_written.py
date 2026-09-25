# -*- coding: utf-8 -*-
"""The panel never offers a log file that nothing writes any more.

THE OPERATOR (2026-09-25): "are the logs perfect now?" In the running bot, very
nearly. In the PANEL, no - and this is the worst thing found all day.

    GET /logs_bp/application_logs   ->   HTTP 200, 41 KB

    2025-11-21 00:14:22,031 WARN exited: discord-bot (exit status 1; not expected)
    2025-11-21 00:14:23,033 INFO spawned: 'discord-bot' with pid 821

That is supervisord output from 21 November 2025, served today, under a tab
labelled Application. DDC has not run under supervisord since the move to a
single process; the container has no supervisorctl at all (checked: `command -v
supervisord` answers nothing). But /app/logs/supervisord.log was left behind,
3.2 MB of it, and the reader finds the file, so it never reaches its fallback.

WHY IT IS WORSE THAN EVERY OTHER LOG FINDING TODAY. "Attempting regeneration"
was a true sentence about a thing that did not happen, and it cost a wrong
diagnosis. This is a whole file of detailed, plausible, alarming history -
processes exiting unexpectedly, restarts, failures - presented as the present.
Anybody debugging DDC today would read it and conclude the bot is crash-looping.

THE PATTERN, NOT THE SYMPTOM. Three of the four sources name files nothing
writes: bot.log, webui_error.log and supervisord.log. Two of them are harmless
TODAY only because they happen not to exist - the reader falls through to the
live container log. Restore an old backup, or run an older image once, and
either becomes the same trap. Only `discord.log` is real.

WHAT DDC ACTUALLY WRITES, and the whole of it: discord.log (INFO and above) and
bot_error.log (ERROR and above), both from app/bootstrap/runtime.py, plus one
file per logger name from utils/logging_utils.setup_logger - which is where
user_actions.log comes from. Nothing else.

bot_error.log was written and offered nowhere when this was found. The
operator's answer to that, the same afternoon, was to put it in the Application
tab - the source this commit had just emptied. See
test_the_application_tab_shows_what_went_wrong.py.

HOW THIS TEST CAN FAIL: a log source naming a file this application does not
write.

COUNTER-CHECK (2026-09-25): red before - three of the four sources.
"""

import ast
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SKIP = {"tests", ".git", "node_modules", "htmlcov", "venv", ".venv", "docs", "scripts"}
THE_SERVICE = PROJECT / "services" / "web" / "container_log_service.py"


def _files_the_application_writes():
    """Every .log file DDC can create, read out of the code that creates them.

    Two sources, and no others exist:

      * a module that constructs a *FileHandler and names the file in a string
        literal - app/bootstrap/runtime.py, for discord.log and bot_error.log;
      * setup_logger(name), which builds "<name>.log" from the logger's name -
        utils/logging_utils.py:314, which is how user_actions.log appears.

    Read from the syntax tree rather than from the logs directory, because the
    directory is exactly what cannot be trusted here: the file at the heart of
    this finding IS on disk, and has been since last November.
    """
    written = set()
    for path in sorted(PROJECT.rglob("*.py")):
        if SKIP & set(path.relative_to(PROJECT).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        builds_a_file = any(isinstance(node, ast.Call)
                            and ast.unparse(node.func).endswith("FileHandler")
                            for node in ast.walk(tree))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if builds_a_file and node.value.endswith(".log") and len(node.value) > 4:
                    written.add(node.value)
            # setup_logger('ddc.bot') -> ddc_bot.log
            if isinstance(node, ast.Call) and "setup_logger" in ast.unparse(node.func):
                for argument in node.args[:1]:
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        written.add(f"{argument.value.replace('.', '_')}.log")
    return written


def _log_sources():
    """{key: [paths]} as the panel's log service declares them."""
    tree = ast.parse(THE_SERVICE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any("log_paths" in ast.unparse(t)
                                                for t in node.targets):
            if isinstance(node.value, ast.Dict):
                return {key.value: [ast.unparse(v) for v in value.elts]
                        for key, value in zip(node.value.keys, node.value.values)
                        if isinstance(key, ast.Constant) and isinstance(value, ast.List)}
    raise AssertionError("the log service no longer declares its sources")


def test_every_offered_log_is_one_this_application_writes():
    """THE FINDING: three of four sources name dead files, and the one that
    still exists on disk serves ten-month-old supervisord output as current."""
    written = _files_the_application_writes()
    offered = []
    for key, paths in _log_sources().items():
        for path in paths:
            for name in re.findall(r"[\w.-]+\.log", path):
                name = name.split("/")[-1]
                if name not in written:
                    offered.append(f"{key} -> {name}")

    assert sorted(set(offered)) == [], (
        "the panel offers a log nothing writes; if the file happens to exist it "
        f"is served as current, whatever its age: {sorted(set(offered))}")


def test_the_dead_supervisord_log_is_read_nowhere():
    """The specific trap, by name. DDC has run as ONE process since the
    supervisord era ended; a source pointing back at it can only show history.

    FROM THE SYNTAX TREE, and it caught me immediately. The first version
    searched the file's TEXT, and went red on the comment that explains why the
    path was removed - the most useful sentence in the module. A comment is not
    a code path; only a string the program can open is. Parsing draws exactly
    that line, and it is the same mistake this file exists to stop: reading
    characters instead of the decision behind them.
    """
    tree = ast.parse(THE_SERVICE.read_text(encoding="utf-8"))
    reads = [ast.unparse(node) for node in ast.walk(tree)
             if isinstance(node, ast.Constant) and isinstance(node.value, str)
             and "supervisord.log" in node.value]

    assert reads == [], (
        f"the Application tab still reads supervisord.log - 3.2 MB from 2025-11-21: {reads}")


def test_the_scan_knows_what_is_written():
    """Counter-check, the one nine sabotages have walked past: a scan that
    finds nothing written would pass the case above by calling every source
    dead, and one that finds everything would pass it by calling nothing dead."""
    written = _files_the_application_writes()

    assert "discord.log" in written, written
    assert "bot_error.log" in written, written
    assert "supervisord.log" not in written, "supervisord.log counted as written"
    assert "bot.log" not in written, "bot.log counted as written"


def test_the_real_log_is_still_offered():
    """The opposite mistake: emptying every source would pass the first case
    and take the working Discord log with it."""
    offered = " ".join(path for paths in _log_sources().values() for path in paths)

    assert "discord.log" in offered, "the one log DDC actually writes is no longer offered"


def test_a_source_with_no_file_still_has_a_way_to_answer():
    """Dropping a dead path must not leave a tab that can only fail. Each
    reader falls through to the live container output, which in a one-process
    DDC is the application log."""
    tree = ast.parse(THE_SERVICE.read_text(encoding="utf-8"))
    for name in ("_get_bot_logs", "_get_webui_logs", "_get_application_logs"):
        reader = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == name)

        assert "_get_filtered_container_logs" in ast.unparse(reader), (
            f"{name} has no fallback, so its tab would answer nothing at all")

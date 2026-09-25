# -*- coding: utf-8 -*-
"""The Application tab shows the errors, and they outlive the container.

THE OPERATOR (2026-09-25), choosing between three ways to use bot_error.log:
show it in the Application tab. It had been written since the beginning -
ERROR and above, rotated at 5 MB with three backups - and displayed nowhere.

WHAT THE TAB SHOWED BEFORE. Its source was supervisord.log, ten months dead
(see test_the_log_page_only_offers_logs_that_are_written.py). With that path
gone it fell through to the container log filtered by
['ERROR', 'WARNING', 'INFO', 'DEBUG', 'Starting', ...] - a list that matches
every line the bot has ever written, so the tab showed everything and meant
nothing.

WHY THIS FILE IS THE RIGHT ONE FOR IT. Every other source in the panel reads
`docker logs`, which is emptied by a rebuild - and DDC is deployed by
rebuilding, so the evidence disappears exactly when somebody goes looking for
it after an upgrade. bot_error.log is on the mounted volume: it survives the
rebuild, the restart and the host reboot. It is the only place an error from
last week still exists.

AND IT IS ONLY WORTH SHOWING BECAUSE OF THE COMMIT BEFORE THIS ONE. Until
then, 33,126 of its 33,216 lines were one missing token reported 11,042 times;
a tab pointed at that would have been a tab full of noise.

THE FALLBACK IS NARROWED TO MATCH. If the file is not there - a fresh install,
a cleared volume - the tab still answers from the container log, but filtered
for things that actually went wrong rather than for every log line in
existence.

HOW THIS TEST CAN FAIL: the tab pointing somewhere else, or its fallback going
back to matching everything.

COUNTER-CHECK (2026-09-25): red before - the source was empty and the fallback
matched INFO and DEBUG.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
THE_SERVICE = PROJECT / "services" / "web" / "container_log_service.py"


def _sources():
    tree = ast.parse(THE_SERVICE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any("log_paths" in ast.unparse(t)
                                                for t in node.targets):
            if isinstance(node.value, ast.Dict):
                return {key.value: [ast.unparse(v) for v in value.elts]
                        for key, value in zip(node.value.keys, node.value.values)
                        if isinstance(key, ast.Constant) and isinstance(value, ast.List)}
    raise AssertionError("the log service no longer declares its sources")


def _reader(name):
    tree = ast.parse(THE_SERVICE.read_text(encoding="utf-8"))
    return next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == name)


def _fallback_patterns(name):
    """The filter list handed to _get_filtered_container_logs."""
    for node in ast.walk(_reader(name)):
        if isinstance(node, ast.Call) and "_get_filtered_container_logs" in ast.unparse(node.func):
            for argument in node.args:
                if isinstance(argument, ast.List):
                    return [item.value for item in argument.elts
                            if isinstance(item, ast.Constant)]
    raise AssertionError(f"{name} has no filtered fallback")


def test_the_application_tab_reads_the_error_log():
    """THE OPERATOR'S CHOICE: the one file that outlives a rebuild."""
    paths = " ".join(_sources()["application"])

    assert "bot_error.log" in paths, (
        f"the Application tab does not read the error log: {paths}")


def test_it_looks_in_both_the_container_and_a_local_checkout():
    """The pair every live source carries - the Docker path and the checkout -
    so the panel works when DDC is run from source as well."""
    paths = _sources()["application"]

    assert len(paths) == 2, paths
    assert any("/app/logs/" in p for p in paths), paths
    assert any("local_logs" in p for p in paths), paths


def test_the_fallback_is_about_things_that_went_wrong():
    """THE OTHER HALF. A filter of ['ERROR','WARNING','INFO','DEBUG','Starting']
    matches every line DDC has ever written, which is not a filter at all."""
    patterns = _fallback_patterns("_get_application_logs")

    assert "ERROR" in patterns, patterns
    for matches_everything in ("INFO", "DEBUG"):

        assert matches_everything not in patterns, (
            f"the fallback still matches {matches_everything}, so it shows the whole log")


def test_a_traceback_is_caught_by_the_fallback():
    """Counter-check: narrowing to the literal word ERROR alone would miss the
    three real incidents in the operator's file, which are tracebacks."""
    patterns = [p.lower() for p in _fallback_patterns("_get_application_logs")]

    assert any("traceback" in p or "exception" in p or "critical" in p for p in patterns), (
        f"a crash would not appear in the Application tab: {patterns}")


def test_the_error_log_is_one_the_application_writes():
    """Counter-check against the sibling ratchet: pointing the tab at a file
    nothing writes is exactly the defect this replaces. bot_error.log is
    created in app/bootstrap/runtime.py."""
    runtime = (PROJECT / "app" / "bootstrap" / "runtime.py").read_text(encoding="utf-8")

    assert "bot_error.log" in runtime, "bot_error.log is not written any more"
    assert "RotatingFileHandler" in runtime, "it is no longer rotated, so it would grow forever"


def test_the_other_sources_did_not_quietly_come_back():
    """Counter-check on the whole change: adding a live path must not be an
    excuse to restore the dead ones alongside it."""
    offered = " ".join(path for paths in _sources().values() for path in paths)

    for dead in ("supervisord.log", "webui_error.log", "bot.log'"):

        assert dead not in offered, f"{dead} is being offered again"

# -*- coding: utf-8 -*-
"""Every DDC module logs under a name the log files receive.

THE SECOND HALF of the finding in 0f37b67d. The two rotating files now hang on
the `ddc` logger, so every ddc.* module reaches them. Thirty-one modules are
not under `ddc` at all: they call logging.getLogger(__name__), which names them
services.*, utils.* or app.* - and nothing in DDC attaches a handler to those.

Measured on the operator's machine, from the log of a healthy start:

    lines from any services.* logger, on the console   0
    lines from any services.* logger, in discord.log   0

176 log calls that arrive nowhere. Among them is the mech status cache service,
which is how this was found: the cog announces "Starting MechStatusCacheService
background loop..." and nothing ever answers - not the service's own first
line, not a failure. It could be running perfectly or not at all, and the log
cannot tell you which.

WHAT MAKES IT WORSE THAN QUIET. Nearly half of those calls are logger.error and
logger.warning. A module that fails here fails in silence, and bot_error.log -
which the panel's Application tab shows, and which is the only log that
survives a rebuild - would still be empty afterwards.

THE FIX IS THE NAME, not the handlers. get_module_logger('x') returns
logging.getLogger('ddc.x'), which the files already receive by propagation, and
which setup_logger gives its own console handler exactly as the twenty
already-visible modules have.

WHY `__name__` LOOKED RIGHT. It is the ordinary Python idiom and it is fine in
a project whose handlers sit on the root logger. DDC's do not: they hang on
`ddc`, deliberately, so that a chatty third-party library cannot fill the
operator's files. That choice is what makes the idiom wrong here - and the
cost only shows when somebody opens a file and finds it empty.

HOW THIS TEST CAN FAIL: a module logging under a name outside `ddc`.

COUNTER-CHECK (2026-09-25): red before - thirty-one modules, 176 calls.
"""

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
NOT_APP_CODE = {"tests", ".git", "node_modules", "htmlcov", "venv", ".venv", "docs", "scripts"}

# Names DDC deliberately logs under that are NOT ddc.*, each with its reason.
# They are few, they are known, and they have their own handlers.
DELIBERATELY_ELSEWHERE = {
    # The user-action log is its own file with its own rotation, read by the
    # action-log page rather than by discord.log.
    "user_actions",
    # The import diagnostics ride along with py-cord's own logger on purpose,
    # so an import problem appears next to the library's complaint about it.
    "discord.app_commands_import",
}


def _module_loggers():
    """(path, assigned name, the expression) for every module-level logger."""
    for path in sorted(PROJECT.rglob("*.py")):
        if NOT_APP_CODE & set(path.relative_to(PROJECT).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not node.targets:
                continue
            made = ast.unparse(node.value)
            if "getLogger" not in made and "get_module_logger" not in made \
                    and "setup_logger" not in made and "get_logger" not in made:
                continue
            yield path.relative_to(PROJECT), ast.unparse(node.targets[0]), made


def _reaches_the_files(made):
    """True when this expression yields a logger under `ddc`.

    READ THE EXPRESSION, not the module. get_module_logger('x') is
    logging.getLogger('ddc.x') - the indirection is the point, because it is
    the only form that cannot get the prefix wrong.
    """
    if "get_module_logger" in made:
        return True
    for allowed in DELIBERATELY_ELSEWHERE:
        if f"'{allowed}'" in made or f'"{allowed}"' in made:
            return True
    return "'ddc." in made or '"ddc.' in made or made.endswith("'ddc')") \
        or made.endswith('"ddc")')


def test_no_module_logs_where_the_files_cannot_see_it():
    """THE FINDING: 176 calls into nothing, half of them errors and warnings."""
    offenders = []
    for path, name, made in _module_loggers():
        if not _reaches_the_files(made):
            offenders.append(f"{path}: {name} = {made}")

    assert sorted(offenders) == [], (
        "these names are outside `ddc`, where the two rotating files hang, so "
        f"nothing they log reaches discord.log or bot_error.log: {sorted(offenders)}")


def test_the_scan_sees_the_modules_that_are_right():
    """Counter-check, the one ten sabotages have walked past: a scan matching
    nothing passes the case above while proving nothing. Most of DDC already
    does this correctly and must be found."""
    good = [1 for _p, _n, made in _module_loggers() if _reaches_the_files(made)]

    assert len(good) > 40, f"only {len(good)} correct loggers found - the scan is blind"


def test_the_name_test_can_tell_them_apart():
    """The predicate itself, both ways. A version that answered True for
    everything would empty the case above."""

    assert _reaches_the_files("get_module_logger('mech_reset_service')")
    assert _reaches_the_files("logging.getLogger('ddc.docker_control')")
    assert _reaches_the_files("get_action_logger()") is False
    assert _reaches_the_files("logging.getLogger(__name__)") is False
    assert _reaches_the_files("logging.getLogger('services.mech.x')") is False


def test_the_files_still_hang_where_every_ddc_name_passes():
    """The other half of the pair (0f37b67d). Renaming every module is worth
    nothing if the handlers move back down onto one of them."""
    source = (PROJECT / "app" / "bot" / "runtime.py").read_text(encoding="utf-8")
    calls = [node for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call)
             and ast.unparse(node.func).endswith("ensure_log_files")]

    assert calls, "nothing attaches the log files any more"
    for call in calls:
        given = ast.unparse(call.args[0])

        assert "ddc" in given and "ddc.bot" not in given, given

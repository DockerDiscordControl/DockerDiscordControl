# -*- coding: utf-8 -*-
"""The temporary debug mode is gone, in all four layers or none.

IT HAD NO WAY IN SINCE 2025-08-12. That day 756bf8df, the security and logging
overhaul, took three elements out of ``_log_section.html``::

    <button type="button" id="enableTempDebugBtn" class="btn btn-sm btn-warning me-2">
    <select id="tempDebugDuration" class="form-select form-select-sm" ...>
    <div id="tempDebugStatus" class="small text-muted">Temporary debug mode is inactive</div>

and left everything behind them standing: the JavaScript whose only entry
point is a listener on ``enableTempDebugBtn``, three Flask routes, three
methods of DiagnosticsService, and three functions in utils/logging_utils.
Four layers deep, thirteen months, and every one of them answering. The route
still returns 200 to this day - measured on the running container - but no
control has ever called it, and nothing outside those layers ever did either.

THAT IS THE WEEK'S SHAPE AT ITS LARGEST: not a button that does nothing, but a
whole feature the code describes and the panel does not have.

WHY REMOVED AND NOT RESTORED. Restoring means three labels, and a label means
forty catalogues - text that would have to be invented rather than translated,
which this project does not do. The switch the overhaul replaced it with is
there and, since 0403a4b4 on 2026-09-24, finally works. The implementation is
not lost: it is complete in the history at 756bf8df~1, which is where to look
if the permanent switch should ever learn to expire by itself.

REMOVED IN ALL FOUR LAYERS, which is the whole point of this file. A stump is
how this started: markup went and the rest stayed, and each layer made the one
below it look wanted.

HOW THIS TEST CAN FAIL: any layer of it coming back, or the permanent debug
switch going with it.

COUNTER-CHECK (2026-09-26): red before on every layer.
"""

import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]

THE_THREE_ELEMENTS = ("enableTempDebugBtn", "tempDebugDuration", "tempDebugStatus")
WHERE_TO_LOOK = ("app", "services", "utils", "cogs")


def _sources():
    for folder in WHERE_TO_LOOK:
        for suffix in ("*.py", "*.js", "*.html"):
            for path in sorted((PROJECT / folder).rglob(suffix)):
                yield path


def test_no_script_looks_for_a_control_that_is_not_there():
    """LAYER ONE. Every one of these lookups returns null, so the listener is
    never attached and nothing below it can ever run."""
    found = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for element in THE_THREE_ELEMENTS:
            if element in text:
                found.append(f"{path.relative_to(PROJECT)}: {element}")

    assert found == [], "the temporary debug controls are still addressed:\n  " + "\n  ".join(found)


def test_the_panel_exports_no_url_for_it():
    """LAYER TWO. Three route names were handed to the browser on every page
    load for a feature the page has no control for."""
    scripts = (PROJECT / "app" / "templates" / "_scripts.html").read_text(encoding="utf-8")

    for name in ("tempDebugStatus", "enableTempDebug", "disableTempDebug"):
        assert name not in scripts, f"_scripts.html still exports {name}"


def test_no_route_answers_for_it():
    """LAYER THREE. Three authenticated endpoints that turn debug logging on
    and off, offered by no control."""
    routes = (PROJECT / "app" / "blueprints" / "main_routes.py").read_text(encoding="utf-8")

    for path in ("/enable_temp_debug", "/disable_temp_debug", "/temp_debug_status"):
        assert path not in routes, f"main_routes.py still answers {path}"


def test_the_service_and_the_helper_are_gone_too():
    """LAYERS THREE AND FOUR. A service method nobody calls and a helper
    nobody calls are what made the layers above look wanted."""
    service = (PROJECT / "services" / "web" / "diagnostics_service.py").read_text(encoding="utf-8")

    for name in ("enable_temp_debug", "disable_temp_debug", "temp_debug_status"):
        assert f"def {name}" not in service, f"DiagnosticsService still has {name}"

    logging_utils = (PROJECT / "utils" / "logging_utils.py").read_text(encoding="utf-8")

    for name in ("enable_temporary_debug", "disable_temporary_debug",
                 "get_temporary_debug_status"):
        assert f"def {name}" not in logging_utils, f"logging_utils still has {name}"


def test_the_permanent_debug_switch_is_untouched():
    """THE OPPOSITE MISTAKE, and the one that would cost something. The
    switch the overhaul replaced it with is the panel's only debug control,
    it was itself broken until 2026-09-24, and everything below it - the
    filter, the level check, the handler pass - has to stay exactly where it
    is."""
    logging_utils = (PROJECT / "utils" / "logging_utils.py").read_text(encoding="utf-8")

    for name in ("def is_debug_mode_enabled", "class DebugModeFilter",
                 "def _apply_debug_levels", "def refresh_debug_status"):
        assert name in logging_utils, f"{name} went with the temporary mode"

    section = (PROJECT / "app" / "templates" / "_log_section.html").read_text(encoding="utf-8")

    assert "debugLevelToggle" in section, "the panel's debug switch is gone"


def test_the_level_check_still_answers_a_plain_true_or_false():
    """It used to end with ``_debug_mode_enabled or _temp_debug_mode_enabled``,
    and the second name was what turned a None - the value before any config
    has been read - into a False. Removing it without noticing would have made
    the function return None, which is falsy but is not a bool, to a filter
    whose whole job is to answer yes or no."""
    import utils.logging_utils as logging_utils

    logging_utils._debug_mode_enabled = None
    answer = logging_utils.is_debug_mode_enabled()

    assert answer is False or answer is True, repr(answer)


def test_the_scan_looks_at_the_whole_panel():
    """The counter-check: every case above passes on an empty file list."""
    files = list(_sources())

    assert len(files) > 250, len(files)
    assert any(path.name == "panel.js" for path in files)
    assert any(path.name == "logging_utils.py" for path in files)

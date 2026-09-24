# -*- coding: utf-8 -*-
"""Turning the debug level on takes effect at once, and on the right switch.

THE OPERATOR ASKED (2026-09-24): "can the debug level activate extended logging
immediately?" The panel says it cannot - "changes take effect after a container
restart". Measured, that note was covering for two separate breaks.

BREAK ONE: TWO SWITCHES, NEITHER CONNECTED TO THE OTHER.

    the panel's box writes   debug_level_enabled   (name of the form field)
    the machinery reads      scheduler_debug_mode  (is_debug_mode_enabled)

`is_debug_mode_enabled()` is what DebugModeFilter consults, and that filter is
what actually lets a DEBUG record through. So the box the operator ticks has
never been able to reach it, whatever else was fixed. Both keys are absent from
his saved configuration, which is consistent with neither switch ever having
been written.

BREAK TWO: THE LEVELS WERE ONLY HALF SET. `_update_logging_settings` lowered
the LOGGERS on save and left the HANDLERS where they were. A record passes a
logger's level and then the handler's, so a logger at DEBUG feeding a handler
at INFO emits nothing - which looks exactly like "you need to restart". Review
C9 found this same half-measure once before, in the temporary debug switch, and
the fix it produced (`_apply_debug_levels`, lowering loggers AND the handlers
that carry a DebugModeFilter) was never wired to the permanent one.

SO NOTHING NEW HAD TO BE BUILT. `refresh_debug_status()` already drops the
config cache, re-reads the flag and applies both halves of the level. It was
called from the diagnostics page and from nowhere else. The save calls it now,
and the restart note is gone from the panel.

THE LEGACY KEY IS STILL READ, second. An installation that has
`scheduler_debug_mode: true` in its config keeps its debug logging; the panel
writes the clearer name from now on.

HOW THIS TEST CAN FAIL: the two keys drifting apart again, a save that does not
apply the level, or handlers left out of it.

COUNTER-CHECK (2026-09-24): red before - is_debug_mode_enabled read only
scheduler_debug_mode, the save called neither refresh_debug_status nor anything
that touched a handler, and the panel carried the restart note.
"""

import json
import logging
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
LOG_SECTION = PROJECT / "app" / "templates" / "_log_section.html"


@pytest.fixture
def config(tmp_path, monkeypatch):
    """A configuration directory of this test's own."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    import utils.logging_utils as logging_utils

    monkeypatch.setattr(logging_utils, "_debug_mode_enabled", None, raising=False)
    return tmp_path


def _say(monkeypatch, **values):
    """Make load_config answer with exactly these keys."""
    import utils.logging_utils as logging_utils
    import services.config.config_service as config_service

    class _Service:
        def get_config(self, force_reload=False):
            return dict(values)

        class _Cache:
            @staticmethod
            def invalidate_cache():
                return None

        _cache_service = _Cache()

    monkeypatch.setattr(config_service, "get_config_service", lambda: _Service())
    monkeypatch.setattr(logging_utils, "_debug_mode_enabled", None, raising=False)


def test_the_panels_own_key_switches_debug_on(config, monkeypatch):
    """THE FIRST BREAK: the box writes one name and the machinery read another."""
    from utils.logging_utils import is_debug_mode_enabled

    _say(monkeypatch, debug_level_enabled=True)

    assert is_debug_mode_enabled() is True


def test_the_legacy_key_still_counts(config, monkeypatch):
    """An installation that already has the old name keeps its debug logging."""
    from utils.logging_utils import is_debug_mode_enabled

    _say(monkeypatch, scheduler_debug_mode=True)

    assert is_debug_mode_enabled() is True


def test_neither_key_means_off(config, monkeypatch):
    from utils.logging_utils import is_debug_mode_enabled

    _say(monkeypatch)

    assert is_debug_mode_enabled() is False


def test_the_panels_key_wins_over_the_legacy_one(config, monkeypatch):
    """They can disagree only while an old configuration is being replaced, and
    the one the operator just ticked is the one he means."""
    from utils.logging_utils import is_debug_mode_enabled

    _say(monkeypatch, debug_level_enabled=False, scheduler_debug_mode=True)

    assert is_debug_mode_enabled() is False


def test_applying_the_level_lowers_the_handlers_too():
    """THE SECOND BREAK: a logger at DEBUG feeding a handler at INFO emits
    nothing, which looks exactly like "restart required"."""
    from utils.logging_utils import DebugModeFilter, _apply_debug_levels

    logger = logging.getLogger("ddc.test_debug_switch")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.addFilter(DebugModeFilter())
    logger.addHandler(handler)
    try:
        _apply_debug_levels(True)

        assert logger.level == logging.DEBUG
        assert handler.level == logging.DEBUG, "the handler still swallows DEBUG"

        _apply_debug_levels(False)

        assert logger.level == logging.INFO
        assert handler.level == logging.INFO, "the old level was not put back"
    finally:
        logger.removeHandler(handler)


def test_the_save_applies_it_at_once():
    """Read from the syntax tree: the save must call the function that does
    both halves, not the one that did loggers only."""
    import ast

    source = (PROJECT / "services" / "web"
              / "configuration_save_service.py").read_text(encoding="utf-8")
    called = {ast.unparse(node.func) for node in ast.walk(ast.parse(source))
              if isinstance(node, ast.Call)}

    assert any("refresh_debug_status" in name for name in called), (
        "the save does not apply the debug level, so it waits for a restart")


def test_the_panel_no_longer_promises_a_restart():
    """The note was true while the switch did nothing. It is not any more."""
    markup = LOG_SECTION.read_text(encoding="utf-8")

    assert "debug_level_restart_hint" not in markup, (
        "the panel still tells the operator to restart for a setting that is live")


def test_the_restart_note_left_every_catalogue():
    """A key dropped from the markup and left in the catalogues is a text
    nobody shows and nobody can find."""
    left = []
    for path in sorted((PROJECT / "locales").glob("*.json")):
        if path.name == "meta.json":
            continue
        if "web.logs.debug_level_restart_hint" in json.loads(path.read_text(encoding="utf-8")):
            left.append(path.name)

    assert left == [], f"the dropped note is still in {len(left)} catalogues: {left[:5]}"

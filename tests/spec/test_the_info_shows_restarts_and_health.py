# -*- coding: utf-8 -*-
"""The container info shows the restart count and the health check (Phase 4e).

Roadmap Phase 4e: "runtime and restart counter in the info modal". The
restart count and health now sit in the status cache (watchdog, Phase 4a),
so the info embed can show them without asking Docker again. The uptime is
deliberately not repeated: _get_status_info says it is already in the status
embed right above the info, and that decision stands.

COUNTER-CHECK (2026-09-22): red before; with no cache entry the info adds
nothing - no invented zero.
"""

from types import SimpleNamespace

from cogs.status_info_integration import StatusInfoButton


def _button(entry):
    button = StatusInfoButton.__new__(StatusInfoButton)
    button.container_name = "web"
    button.cog = SimpleNamespace(status_cache_service=SimpleNamespace(get=lambda name: entry))
    return button


def test_restarts_and_health_are_shown():
    entry = {"data": SimpleNamespace(success=True, restart_count=3, health="unhealthy")}
    text = _button(entry)._get_status_info()
    assert "3" in text and "unhealthy" in text


def test_no_health_check_means_no_health_line():
    entry = {"data": SimpleNamespace(success=True, restart_count=0, health=None)}
    text = _button(entry)._get_status_info()
    assert "0" in text and "health" not in text.lower()


def test_nothing_known_means_nothing_shown():
    assert _button(None)._get_status_info() is None
    entry = {"data": SimpleNamespace(success=True, restart_count=None, health=None)}
    assert _button(entry)._get_status_info() is None

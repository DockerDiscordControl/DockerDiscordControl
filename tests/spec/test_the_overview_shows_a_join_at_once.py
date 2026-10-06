# -*- coding: utf-8 -*-
"""The overview shows a changed player count at the next beat, not at its interval.

THE FINDING (operator, 2026-10-06, a screenshot: the join notice "Ein Spieler
ist auf Valheim gekommen (1/10)" at 19:47, the overview above it still from
the update before): the overview was redrawn only at the channel's update
interval, so a join stood in the channel for up to ten minutes while the
overview said otherwise.

THE CONTRACT: when a game server's player count differs from the last beat's,
every overview whose auto-refresh is on is redrawn in this beat; a count that
could not be read changes nothing; a stopped server counts as 0; the first
beat only remembers; auto-refresh switched off stays off.

HOW THIS TEST CAN FAIL: a change that waits for the interval, a failed query
that redraws, or the edit loop not asking.

COUNTER-CHECK (2026-10-06): red on the code before the change (no
players_changed, the interval decided alone).
"""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from services.discord.status_overview_service import StatusOverviewService

ROOT = Path(__file__).resolve().parents[2]


def _config(auto_refresh=True):
    return {"channel_permissions": {"1": {"enable_auto_refresh": auto_refresh, "update_interval_minutes": 10,
                                          "recreate_messages_on_inactivity": False}}}


def test_a_change_redraws_before_the_interval():
    service = StatusOverviewService()
    just_now = datetime.now(timezone.utc) - timedelta(minutes=1)
    quiet = service.make_update_decision(1, _config(), last_update_time=just_now, beat_seconds=60)
    changed = service.make_update_decision(1, _config(), last_update_time=just_now, beat_seconds=60,
                                           players_changed=True)
    assert quiet.should_update is False, "premise: the interval alone says no"
    assert changed.should_update is True


def test_auto_refresh_switched_off_stays_off():
    decision = StatusOverviewService().make_update_decision(1, _config(auto_refresh=False),
                                                            players_changed=True)
    assert decision.should_update is False


def _cog(cache):
    from cogs.docker_control import DockerControlCog
    cog = object.__new__(DockerControlCog)
    cog.status_cache_service = SimpleNamespace(get=lambda name: cache.get(name))
    return cog


def _entry(players, running=True, success=True):
    return {"data": SimpleNamespace(success=success, is_running=running, players_online=players)}


def test_the_count_comparison(monkeypatch):
    servers = [{"docker_name": "Valheim", "query_enabled": True},
               {"docker_name": "nginx", "query_enabled": False}]
    monkeypatch.setattr("services.config.server_config_service.get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: servers))
    cache = {"Valheim": _entry(0), "nginx": _entry(None)}
    cog = _cog(cache)

    assert cog._player_counts_changed() is False, "the first beat only remembers"
    assert cog._player_counts_changed() is False, "nothing changed"
    cache["Valheim"] = _entry(1)
    assert cog._player_counts_changed() is True, "a join"
    cache["Valheim"] = _entry(None)
    assert cog._player_counts_changed() is False, "a failed query redraws nothing"
    cache["Valheim"] = _entry(1)
    assert cog._player_counts_changed() is False, "back to what was known: no change"
    cache["Valheim"] = _entry(None, running=False)
    assert cog._player_counts_changed() is True, "a stopped server counts as 0"


def test_the_edit_loop_asks_and_passes_it_on():
    source = (ROOT / "cogs" / "message_updates.py").read_text(encoding="utf-8")
    assert "players_changed = self._player_counts_changed()" in source
    assert len(re.findall(r"players_changed=players_changed", source)) == 2, \
        "both the overview and the admin overview must hear of the change"

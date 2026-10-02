# -*- coding: utf-8 -*-
"""An empty mech is said in the log when it runs dry and when it has power again - not every cycle.

THE OBSERVATION (2026-10-02, agreed with the operator): while the mech had no
power, two loops - the mech decay worker (app/utils/web_helpers.py) and the
mech status cache refresh - each wrote "Mech is OFFLINE (Power: $0.00)" at
INFO every 30 seconds: 10 lines in the first minutes after a rebuild, 5,760
a day, burying the lines that mean something.

THE CONTRACT: one INFO line when the mech runs dry, one when it has power
again, shared by both loops; the first look after a start says the state
once.

HOW THIS TEST CAN FAIL: a cycle repeats the line, a change goes unsaid, or
the two loops say the same change twice.

COUNTER-CHECK (2026-10-02): red before the change (a line per cycle and per
loop).
"""

from types import SimpleNamespace

import pytest

import services.mech.mech_power_notice as notice


@pytest.fixture
def said(monkeypatch):
    lines = []
    monkeypatch.setattr(notice, "_last_offline", None)
    monkeypatch.setattr(notice.logger, "info", lambda message, *a, **k: lines.append(str(message)))
    return lines


def _state(offline, power=0.0):
    return SimpleNamespace(is_offline=offline, power_current=power)


def test_each_change_is_said_once(said):
    for state in [_state(True)] * 4 + [_state(False, 4.5)] * 3 + [_state(True)] * 2:
        notice.note_power_state(state)
    assert len(said) == 3, said
    assert "no power" in said[0] and "4.50" in said[1] and "no power" in said[2]


@pytest.mark.asyncio
async def test_both_loops_share_it(said, monkeypatch):
    from services.mech.mech_status_cache_service import MechStatusCacheService
    monkeypatch.setattr("services.mech.progress_service.get_progress_service",
                        lambda: SimpleNamespace(get_state=lambda: _state(True)))
    notice.note_power_state(_state(True))          # the decay worker saw it first
    service = MechStatusCacheService.__new__(MechStatusCacheService)
    quiet = lambda *a, **k: None  # noqa: E731
    # The service's own logger is listened to as well: it wrote the line itself
    service.logger = SimpleNamespace(info=lambda message, *a, **k: said.append(str(message)),
                                     debug=quiet, warning=quiet, error=quiet)

    async def nothing(*args, **kwargs):
        return None
    monkeypatch.setattr(service, "_refresh_cache", nothing, raising=False)
    try:
        await service._background_refresh()
    except (AttributeError, TypeError, KeyError, RuntimeError):
        pass                                      # what follows the decay part is not under test
    offline_lines = [line for line in said if "power" in line.lower() or "OFFLINE" in line]
    assert len(offline_lines) == 1, f"the cache refresh said it again: {said}"

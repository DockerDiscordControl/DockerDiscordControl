# -*- coding: utf-8 -*-
"""The 15-minute probe window closes, in the order the status loop runs it.

THE FINDING (stage 4 review before v3.1.0, section 20, verifier N1): every
status pass calls reload(), which replaced the in-memory entry - and its
'updated' - with the file's copy. The file's 'updated' is the time of the
last WRITE, and a still-probing container is written only when a verdict
field changes. So 300 s after the last write, record_result saw a "gap",
restarted the window and wrote; five minutes later again. The window never
closed: no container ever became final "unsupported", and every online
container that does not answer (every non-game container) was probed every
60 s forever instead of for 15 minutes.

THE CONTRACT: the gap is measured from this process's last probe result,
which a reload does not touch; after 15 silent minutes the verdict is final.
A real gap (DDC was down, nothing in memory) still starts a fresh window.

HOW THIS TEST CAN FAIL: the window keeps moving and the entry never turns
final, or a real gap no longer resets it.

COUNTER-CHECK (2026-09-30): red before the change (final stayed False).
"""

import time

from services.infrastructure.game_query_support_service import (
    GameQuerySupportService, _read_verdicts_at)

T0 = 1_000_000.0


def test_twenty_silent_minutes_end_the_window(tmp_path, monkeypatch):
    clock = [T0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    path = tmp_path / "query_support.json"
    svc = GameQuerySupportService(path=path)
    # The pass order of cogs/status_handlers.py: reload, then probe what is due
    for step in range(40):
        clock[0] = T0 + step * 30
        svc.reload()
        if svc.should_probe("c", clock[0]):
            svc.mark_probed("c", clock[0])
            svc.record_result("c", False, now_wall=clock[0])
    entry = _read_verdicts_at(path)["c"]
    assert (entry["final"], entry["supported"]) == (True, False)


def test_a_restart_after_a_long_pause_starts_a_fresh_window(tmp_path, monkeypatch):
    clock = [T0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    path = tmp_path / "query_support.json"
    GameQuerySupportService(path=path).record_result("c", False, now_wall=T0)
    clock[0] = T0 + 3600          # DDC was down for an hour
    fresh = GameQuerySupportService(path=path)
    fresh.record_result("c", False, now_wall=clock[0])
    entry = _read_verdicts_at(path)["c"]
    assert entry["final"] is False and entry["probing_since"] == clock[0]

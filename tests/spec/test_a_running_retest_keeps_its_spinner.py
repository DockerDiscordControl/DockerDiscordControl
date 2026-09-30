# -*- coding: utf-8 -*-
"""A manual re-test keeps its "testing" flag while the bot writes the verdict.

THE FINDING (stage 4 review before v3.1.0, section 20, pass 3 F5 and pass 4
F3): a manual re-test sets 'testing': True in the shared file, and the
panel polls it every 3 s. The bot's _set wrote a fresh entry without
'testing' over the whole key whenever a verdict field changed, and
note_offline removed the key. The panel then saw testing=False and
supported=False, stopped, and said "No response" while the re-test worker
(3 tries, 60 s apart) was still running; a later success stayed invisible
until a reload.

THE CONTRACT: the bot's writes keep a 'testing' flag the web process set.

HOW THIS TEST CAN FAIL: a verdict change or an offline container clears
the flag again.

COUNTER-CHECK (2026-09-30): red before the change (the flag was gone).
"""

import time

from services.infrastructure.game_query_support_service import (
    GameQuerySupportService, _read_verdicts_at)

T0 = 1_000_000.0


def _probing(tmp_path, monkeypatch):
    clock = [T0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    path = tmp_path / "query_support.json"
    svc = GameQuerySupportService(path=path)
    svc.record_result("c", False, now_wall=T0)
    svc.set_testing("c", True)          # the web process starts a re-test
    svc.reload()
    return svc, path, clock


def test_a_verdict_change_keeps_the_flag(tmp_path, monkeypatch):
    svc, path, clock = _probing(tmp_path, monkeypatch)
    clock[0] = T0 + 400                 # past the gap reset: the window restarts
    svc.record_result("c", False, now_wall=clock[0])
    entry = _read_verdicts_at(path)["c"]
    assert entry["probing_since"] == clock[0], "no verdict field changed - the test proves nothing"
    assert entry.get("testing") is True


def test_going_offline_keeps_the_flag(tmp_path, monkeypatch):
    svc, path, _clock = _probing(tmp_path, monkeypatch)
    svc.note_offline("c")
    assert _read_verdicts_at(path)["c"].get("testing") is True

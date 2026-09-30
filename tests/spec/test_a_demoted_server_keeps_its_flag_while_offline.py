# -*- coding: utf-8 -*-
"""A server that answered once keeps its "demoted" flag while it is offline.

THE FINDING (stage 4 review before v3.1.0, section 20 pass 4 F1):
note_offline deleted every entry that was not final, a demoted one too (a
server that answered once, then failed three live queries), and the flag
went with it. Back online and silent for the 15-minute window, the server
became final "unsupported" instead of "silent" - and should_probe never
asked it again. That is exactly what the flag exists to prevent (module
doc: the crashed Enshrouded server). Latent while the window never closed
(finding 20#9), live once it does.

THE CONTRACT: going offline resets a demoted server's window but keeps the
flag; it ends "silent" and is asked again after DEMOTED_RETRY_SECONDS.

HOW THIS TEST CAN FAIL: the flag is dropped again and the server is never
probed after its window.

COUNTER-CHECK (2026-09-30): red before the change (final without demoted,
should_probe False).
"""

import time

from services.infrastructure.game_query_support_service import (
    DEMOTED_RETRY_SECONDS, GameQuerySupportService, _read_verdicts_at)

T0 = 1_000_000.0


def test_a_demoted_server_that_went_offline_is_asked_again(tmp_path, monkeypatch):
    clock = [T0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    path = tmp_path / "query_support.json"
    svc = GameQuerySupportService(path=path)
    svc.record_result("g", True, "source", 27015)
    for _ in range(3):
        svc.note_query_failure("g")
    assert svc._state["g"]["demoted"] is True
    svc.note_offline("g")

    # Back online, silent: one probe a minute through the whole window
    for step in range(16):
        clock[0] = T0 + 600 + step * 60
        svc.record_result("g", False, now_wall=clock[0])

    entry = _read_verdicts_at(path)["g"]
    assert (entry["final"], entry["supported"], entry.get("demoted")) == (True, False, True)
    svc.mark_probed("g", 0.0)
    assert svc.should_probe("g", DEMOTED_RETRY_SECONDS) is True


def test_an_ordinary_probing_container_still_starts_afresh(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: T0)
    path = tmp_path / "query_support.json"
    svc = GameQuerySupportService(path=path)
    svc.record_result("app", False, now_wall=T0)
    svc.note_offline("app")
    assert "app" not in _read_verdicts_at(path)

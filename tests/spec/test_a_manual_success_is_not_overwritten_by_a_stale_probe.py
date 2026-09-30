# -*- coding: utf-8 -*-
"""A manual re-test's success is not overwritten by the bot's older failed probe.

THE FINDING (stage 4 review before v3.1.0, section 20 pass 4 F2): the bot
decides from the state reload() read at the start of its probe pass, and
_set compared against that stale copy too. A manual re-test that succeeded
between the reload and the bot's failed probe of the same container was
replaced by supported=False when the bot's result changed a verdict field -
and final "unsupported" when the window gave up, never probed again until
another manual re-test.

THE CONTRACT: under the file lock, a final supported entry on disk wins
over a negative result of the bot, and the bot adopts it.

HOW THIS TEST CAN FAIL: the web process's success is lost again.

COUNTER-CHECK (2026-09-30): red before the change (supported False, final True).
"""

import time

from services.infrastructure.game_query_support_service import (
    PROBE_WINDOW_SECONDS, GameQuerySupportService, _read_verdicts_at)

T0 = 1_000_000.0


def test_the_web_processs_success_survives(tmp_path, monkeypatch):
    clock = [T0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    path = tmp_path / "query_support.json"
    svc = GameQuerySupportService(path=path)
    for step in range(15):                       # probing, one probe a minute
        clock[0] = T0 + step * 60
        svc.record_result("c", False, now_wall=clock[0])
    svc.reload()                                 # the start of the next pass

    # Meanwhile the web process's re-test answers (its own function, same file)
    from services.infrastructure.game_query_support_service import record_manual_success
    record_manual_success("c", "source", 27015, path=path)

    clock[0] = T0 + PROBE_WINDOW_SECONDS         # the bot's probe failed: its window gives up
    svc.record_result("c", False, now_wall=clock[0])

    entry = _read_verdicts_at(path)["c"]
    assert (entry["supported"], entry["final"], entry["port"]) == (True, True, 27015)
    assert svc.is_supported("c") is True, "the bot kept its stale verdict in memory"

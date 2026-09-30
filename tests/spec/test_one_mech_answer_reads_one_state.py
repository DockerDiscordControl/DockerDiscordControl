# -*- coding: utf-8 -*-
"""One mech answer is built from one reading of the progress state.

THE FINDING (stage 4 review before v3.1.0, section 22, pass 3 F2 and pass 4
F4): get_comprehensive_data read ProgressService.get_state() three times -
for the core data (through the mech service), for the evolution data and
for the bars - each under its own lock. A donation or level-up booked in
between gave an answer that mixed levels (current level from N, level
name, next level, threshold and bars from N+1), cached for 10 s.

THE CONTRACT: every level field of one answer comes from one reading.
(_get_technical_data reads the state a further time, for two constants
that do not depend on it; that reading is harmless and left alone.)

HOW THIS TEST CAN FAIL: a second reading comes back and the fields split
between two levels.

COUNTER-CHECK (2026-09-30): red before the change (level 2 next to
next_level 4 and threshold 55).
"""

import importlib

from services.mech.mech_data_store import MechDataRequest, get_mech_data_store


def _state(level, evo_max):
    # The module as it is NOW: other spec files reload progress_service, and a
    # ProgressState of the old module is not one of the new (2026-09-30)
    progress_service = importlib.import_module("services.mech.progress_service")
    return progress_service.ProgressState(level=level, power_current=5.0, power_max=40.0, power_percent=12,
                         evo_current=3.0, evo_max=evo_max, evo_percent=10, total_donated=50.0,
                         can_level_up=False, is_offline=False, difficulty_bin=1,
                         difficulty_tier="medium", member_count=10)


def test_a_level_up_between_the_readings_does_not_split_the_answer(monkeypatch):
    calls = []

    def get_state(self):
        calls.append(1)
        # The first reading sees level 2; a donation lifts it to 3 right after.
        # The core data is read first, so level 2 is the answer.
        return _state(2, 30.0) if len(calls) == 1 else _state(3, 55.0)
    # On the objects in use, not on a class: after a reload the mech service
    # may hold an instance of an older ProgressService than the module's
    from services.mech.mech_service import get_mech_service
    progress_service = importlib.import_module("services.mech.progress_service")
    for instance in {id(o): o for o in (get_mech_service().progress_service,
                                         progress_service.get_progress_service())}.values():
        monkeypatch.setattr(instance, "get_state", get_state.__get__(instance))

    result = get_mech_data_store().get_comprehensive_data(MechDataRequest(force_refresh=True))

    assert result.success, result.error
    assert (result.current_level, result.next_level) == (2, 3)
    assert result.next_threshold == 30.0 == result.bars.mech_progress_max
    assert result.bars.Power_max_for_level == 40.0

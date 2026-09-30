# -*- coding: utf-8 -*-
"""A progress config without difficulty bins still prices the next level.

THE FINDING (stage 4 review before v3.1.0, section 24 pass 4 F6): if
config/progress/config.json lacked 'difficulty_bins' (hand-edited, or
holding {} or null - an existing file is never merged with the defaults),
current_bin raised KeyError on the first snapshot creation and at every
level-up - after the donation was appended - and on every heal rebuild, so
bookings failed until the file was repaired. The two sibling price helpers
already fall back with .get().

THE CONTRACT: missing bins mean the default bins.

HOW THIS TEST CAN FAIL: KeyError again.

COUNTER-CHECK (2026-09-30): red before the change (KeyError; an empty list
gave bin 1 for 30 members).
"""

import pytest

from services.mech import progress_service


@pytest.mark.parametrize("cfg", [{}, {"difficulty_bins": None}, {"difficulty_bins": []}])
def test_the_default_bins_apply(monkeypatch, cfg):
    monkeypatch.setattr(progress_service, "CFG", cfg)
    snap = progress_service.Snapshot(mech_id="t")
    progress_service.set_new_goal_for_next_level(snap, user_count=30)
    assert snap.difficulty_bin == 2, "30 members are the second default bin (25 and up)"

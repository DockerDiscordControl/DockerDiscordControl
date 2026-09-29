# -*- coding: utf-8 -*-
"""The difficulty preview in the panel names the mech's real level and its real next price.

THE FINDING (stage 4 review before v3.1.0, section 22 pass 4 F12, verified
2026-09-29 in a corrected form). The Advanced Settings difficulty panel
guessed the level with get_evolution_level(lifetime total) against the
evolution.json base costs, and priced the next level as base_cost ×
multiplier. The real level comes from the progress ledger (its evolution
account restarts at every level-up) and the real price includes the
community part: at $30 lifetime the preview said level 6 while the mech
stood at level 2 or 3, with a price that was not the one it would pay.

THE CONTRACT: the preview (read and after a save) shows the progress
state's level and its current goal as the next price.

HOW THIS TEST CAN FAIL: the preview guesses from the lifetime total again.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

from types import SimpleNamespace


def test_the_preview_shows_the_ledgers_level_and_goal(monkeypatch):
    from services.web import mech_web_service as module

    monkeypatch.setattr("services.mech.mech_data_store.get_mech_data_store", lambda: SimpleNamespace(
        get_evolution_info=lambda req: SimpleNamespace(success=True, difficulty_multiplier=1.0,
                                                       evolution_mode="dynamic", error=None)))
    monkeypatch.setattr("services.mech.progress_service.get_progress_service", lambda *a: SimpleNamespace(
        get_state=lambda: SimpleNamespace(level=2, evo_max=25.0)))
    service = module.MechWebService()
    monkeypatch.setattr(service, "_get_total_donations", lambda: 30.0)

    result = service._get_difficulty()

    evolution = result.data["simple_evolution"]
    assert evolution["current_level"] == 2, evolution
    assert evolution["next_level_cost"] == 25, evolution

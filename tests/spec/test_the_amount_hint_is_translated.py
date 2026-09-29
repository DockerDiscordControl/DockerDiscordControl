# -*- coding: utf-8 -*-
"""The donation window's "Need $X for Level N" hint goes through the translation.

THE FINDING (stage 4 review before v3.1.0, section 06 pass 4 F10): the amount
field's placeholder "💎 Need $X for Level N! (e.g. X)" was a bare f-string.
With a non-English bot and a mech below level 11 - the usual case - this one
field was English while its neighbours and fallbacks were translated.

THE CONTRACT: it is a catalogue entry with {amount} and {level}.

HOW THIS TEST CAN FAIL: the hint bypasses the translation again.

COUNTER-CHECK (2026-09-29): red before the change.
"""

from types import SimpleNamespace

import cogs.translation_manager as tm
from cogs.donation_ui import DonationBroadcastModal


def test_the_hint_is_looked_up(monkeypatch):
    monkeypatch.setattr(tm, "_", lambda text: "«" + text + "»")
    monkeypatch.setattr("services.mech.progress_service.get_progress_service",
                        lambda: SimpleNamespace(get_state=lambda: SimpleNamespace(
                            level=3, evo_max=20, evo_current=5)))
    modal = DonationBroadcastModal.__new__(DonationBroadcastModal)

    hint = modal._get_dynamic_amount_placeholder()

    assert hint.startswith("«"), f"the hint bypassed the translation: {hint!r}"
    assert "15" in hint and "4" in hint, hint

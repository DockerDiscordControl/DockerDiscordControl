# -*- coding: utf-8 -*-
"""A channel entry of the wrong shape is skipped when the control channels are looked up.

THE FINDING (stage 4 review before v3.1.0, section 13 pass 4 F10): a channel
file whose "commands" is null, or an entry that is a list (hand edits), made
control_channel_ids raise AttributeError - breaking the update notice and
the watchdog's default notice channel. The status lookup beside it already
guards both.

THE CONTRACT: such entries are skipped; the others are found.

HOW THIS TEST CAN FAIL: the AttributeError escapes again.

COUNTER-CHECK (2026-09-30): red before the change.
"""

from services.config.channel_roles import control_channel_ids


def test_the_good_channel_is_still_found():
    config = {"channel_permissions": {"1": {"commands": None}, "2": [],
                                      "3": {"commands": {"control": True}}}}
    assert control_channel_ids(config) == [3]

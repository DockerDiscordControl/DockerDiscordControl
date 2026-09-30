# -*- coding: utf-8 -*-
"""A lost release record does not relabel a granted gift as "passed".

THE FINDING (stage 4 review before v3.1.0, section 22 pass 4 F9): when the
event log already holds this version's release gift but
release_gifts_checked.json has no entry for it - the record write at the
first start failed (only a warning), or the file was deleted or unreadable
- the next start asked power_gift again, which refused (campaign used, or
the mech still has the gifted power), and the refusal was recorded as
"passed": "the mech had energy at the first start", which is false. Worse,
"passed" short-circuits before the campaign check, so a gift the admin
later deleted no longer freed the campaign
(test_a_deleted_gift_frees_its_campaign).

THE CONTRACT: the label comes from the ledger. A version whose gift stands
in the event log is recorded "granted", whatever the refusal says.

HOW THIS TEST CAN FAIL: "passed" is recorded again, and the deleted gift
keeps its campaign spent.

COUNTER-CHECK (2026-09-30): red before the change ("passed" recorded, the
last call gave None).
"""

import importlib
import json

from tests.spec.test_a_new_release_refuels_an_empty_mech import (  # noqa: F401 - fixtures
    mech, module)


def _record(gifts):
    path = gifts.DATA_DIR / gifts.RELEASES_CHECKED_FILE
    return json.loads(path.read_text(encoding="utf-8"))["versions"] if path.exists() else {}


def test_a_granted_gift_stays_granted_after_the_record_is_lost(module, mech):
    gifts = importlib.import_module("services.mech.gifts")
    _state, first = mech.release_gift("9.9.9")
    assert first is not None
    (gifts.DATA_DIR / gifts.RELEASES_CHECKED_FILE).unlink()

    _state, again = mech.release_gift("9.9.9")        # the next start
    assert again is None, "the gift was handed out twice"
    assert _record(gifts).get("9.9.9") == "granted"

    gift_event = [e for e in module.read_events() if e.type == "PowerGiftGranted"][-1]
    mech.delete_donation(gift_event.seq)
    _state, after_delete = mech.release_gift("9.9.9")
    assert after_delete is not None, "the deleted gift kept its campaign spent"

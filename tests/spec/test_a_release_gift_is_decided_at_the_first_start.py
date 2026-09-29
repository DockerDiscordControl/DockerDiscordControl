# -*- coding: utf-8 -*-
"""The first start of a release decides its gift - no gift later.

THE FINDING (operator, 2026-09-29). v3.1.0 was first started while the mech
still had energy: no gift, as promised. Days later the mech ran dry, the
container was rebuilt on the same v3.1.0 - and that restart handed out the
release gift ($4.50, three days of level 6). Only a GRANTED gift spent the
campaign, so a refused one stayed open for whichever restart found the mech
empty. The operator: a mech with energy at the release gets no gift at all,
not a delayed one.

THE CONTRACT: the first start of a version records what it decided. A
version it passed over - the mech had energy - gives nothing on a later
start, even for a dry mech. A new version is decided afresh.

HOW THIS TEST CAN FAIL: a restart of a version that found the mech with
energy refuels it once it is dry.

A version whose first start GRANTED the gift keeps the older rule: a gift
the admin deleted frees the campaign (test_a_deleted_gift_frees_its_campaign).

COUNTER-CHECK (2026-09-29): with the "passed" check in gifts.release_gift
removed, the first test goes red - the second start gives $3.00; with every
first start recorded as "passed", the deleted-gift test goes red. The other
two here stay green and hold what must still happen.
"""

from datetime import timedelta

from tests.spec.test_a_new_release_refuels_an_empty_mech import (  # noqa: F401 - fixtures
    _power, mech, module)


def _run_dry(module):
    """Ten days on, a level 1 mech has used up any three days it had."""
    snap = module.load_snapshot("main")
    snap.goal_started_at = (
        module._parse_utc(snap.goal_started_at) - timedelta(days=10)).isoformat()
    module.persist_snapshot(snap)


def _give_energy(module, mech):
    mech.power_gift("some_earlier_gift", gift_cents=200)
    assert _power(module, mech) == 200


def test_a_mech_with_energy_at_the_first_start_gets_nothing_later(module, mech):
    _give_energy(module, mech)
    _state, first = mech.release_gift("3.1.0")
    assert first is None

    _run_dry(module)
    assert _power(module, mech) == 0
    _state, later = mech.release_gift("3.1.0")      # the rebuild days later

    assert later is None, f"a restart of the same release gave {later}"
    assert _power(module, mech) == 0


def test_a_dry_mech_at_the_first_start_still_gets_its_three_days(module, mech):
    """Counter-check: the gift itself is not gone."""
    _state, gift = mech.release_gift("3.1.0")

    assert gift == 3.0


def test_the_next_release_is_decided_afresh(module, mech):
    """Counter-check: recording 3.1.0 does not spend 3.1.1."""
    _give_energy(module, mech)
    mech.release_gift("3.1.0")
    _run_dry(module)

    _state, gift = mech.release_gift("3.1.1")

    assert gift == 3.0

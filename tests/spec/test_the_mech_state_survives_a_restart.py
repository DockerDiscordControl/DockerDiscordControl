#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
THE FINDING (review C5, section 23 F1): a freshly built ``MechStateManager``
starts with an EMPTY cache even when ``mech_state.json`` is full. ``__init__``
sets ``state_cache = {}`` and calls ``_ensure_state_file()``, which only writes
when the file is missing - it never reads. Every write method
(``set_state``, ``set_last_glvl``, ``mark_force_recreate``)
mutates that empty cache and then hands the WHOLE cache to ``save_state``, which
replaces the file. So the first write after a restart throws away everything
that was in the file: the other channels' expanded states, all remembered
Glvl values, and the overview message ids that exist precisely to survive a
restart.

WHAT THE REPORT GOT WRONG, stated plainly: it claimed the deployed bot loses
state. It does not. ``cogs/docker_control.py`` builds the singleton and calls
``load_state()`` on the very next lines, so in the running bot the cache is warm
before anything writes. The defect is in the class, not (today) in the bot: the
manager is only safe because one caller happens to repair it from outside, and
the second production caller - ``status_overview_service`` - relies on that
repair having happened.

Two counter-checks make sure these tests are not simply asserting "the file
never shrinks" - which a save_state that merged into the file instead of
replacing it would satisfy without ever reading anything: a manager started on
an EMPTY file must write only the new key, and a write that REMOVES an entry
must actually remove it on disk.
"""
import json

import pytest

from services.mech.mech_state_manager import MechStateManager


@pytest.fixture
def state_file(tmp_path):
    """A state file as a restart finds it: written by the previous run."""
    path = tmp_path / "mech_state.json"
    path.write_text(json.dumps({
        "last_glvl_per_channel": {"111": 7, "222": 3},
        "channel_overview_message_ids": {"111": {"overview": 500}},
    }))
    return str(path)


def _on_disk(path):
    with open(path) as f:
        return json.load(f)


def test_a_write_for_one_channel_keeps_the_other_channels(state_file):
    """THE FINDING: a write for 222 must not delete 111.

    It used to say set_expanded_state; that setter went with the old shape of
    the overview on 2026-09-25, and the rule belongs to the manager, not to
    the setter that showed it."""
    manager = MechStateManager(state_file=state_file)
    manager.set_last_glvl("222", 5)

    state = _on_disk(state_file)
    assert state["last_glvl_per_channel"] == {"111": 7, "222": 5}


def test_a_write_keeps_the_keys_it_does_not_touch(state_file):
    """The overview message ids exist to survive a restart - a glvl write must
    not be what destroys them."""
    manager = MechStateManager(state_file=state_file)
    manager.set_last_glvl("111", 9)

    state = _on_disk(state_file)
    assert state["channel_overview_message_ids"] == {"111": {"overview": 500}}
    assert state["last_glvl_per_channel"] == {"111": 9, "222": 3}


def test_a_fresh_manager_can_answer_from_the_file(state_file):
    """Reading is wrong too, not just writing: the getters answer from the
    cache, so a fresh manager reported nothing for a channel the file knows."""
    manager = MechStateManager(state_file=state_file)

    assert manager.get_last_glvl("111") == 7


def test_the_check_can_tell_a_loss_from_a_keep(tmp_path):
    """COUNTER-CHECK: the tests above must not pass just because a manager never
    removes anything. On an empty file, a write produces exactly the new key."""
    path = str(tmp_path / "empty_state.json")
    with open(path, "w") as f:
        json.dump({}, f)

    manager = MechStateManager(state_file=path)
    manager.set_last_glvl("333", 4)

    assert _on_disk(path) == {"last_glvl_per_channel": {"333": 4}}


def test_a_removal_still_reaches_the_file(state_file):
    """COUNTER-CHECK: keeping what was not touched must not become "keeping
    everything forever". A save that merges into the on-disk state instead of
    replacing it would pass every test above while making a deletion
    impossible."""
    manager = MechStateManager(state_file=state_file)
    manager.set_state("last_glvl_per_channel", {"222": 3})

    assert _on_disk(state_file)["last_glvl_per_channel"] == {"222": 3}

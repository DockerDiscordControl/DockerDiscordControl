#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for MechStateManager atomic save_state (FIX C prerequisite) and the
channel_overview_message_ids round-trip used to survive bot restarts.
"""
import json
import os

import pytest

from services.mech.mech_state_manager import MechStateManager


@pytest.fixture
def state_file(tmp_path):
    return str(tmp_path / "mech_state.json")


def test_save_and_load_roundtrip(state_file):
    m = MechStateManager(state_file=state_file)
    m.set_state("channel_overview_message_ids", {"111": {"overview": 500}})
    # Fresh manager simulates a restart
    reloaded = MechStateManager(state_file=state_file).load_state()
    assert reloaded["channel_overview_message_ids"] == {"111": {"overview": 500}}


def test_save_is_atomic_no_temp_leftovers(state_file):
    m = MechStateManager(state_file=state_file)
    m.set_state("k", {"a": 1})
    directory = os.path.dirname(state_file)
    leftovers = [f for f in os.listdir(directory) if ".tmp." in f]
    assert leftovers == []
    # File is valid JSON
    with open(state_file) as f:
        json.load(f)


def test_existing_keys_are_preserved_alongside_new_key(state_file):
    m = MechStateManager(state_file=state_file)
    m.set_expanded_state("111", True)
    m.set_last_glvl("111", 7)
    m.set_state("channel_overview_message_ids", {"222": {"admin_overview": 700}})
    state = MechStateManager(state_file=state_file).load_state()
    assert state["mech_expanded_states"] == {"111": True}
    assert state["last_glvl_per_channel"] == {"111": 7}
    assert state["channel_overview_message_ids"] == {"222": {"admin_overview": 700}}


def test_cleans_orphaned_tmp_files_on_init(state_file):
    # Simulate a crash that left a temp file from a previous atomic write.
    directory = os.path.dirname(state_file)
    orphan = os.path.join(directory, os.path.basename(state_file) + ".tmp.99999")
    with open(orphan, "w") as f:
        f.write("partial")
    assert os.path.exists(orphan)
    MechStateManager(state_file=state_file)  # __init__ should sweep it
    assert not os.path.exists(orphan)


def test_recovers_from_preexisting_corrupt_file(state_file):
    # A truncated/corrupt file must not wedge the manager - load returns {} and a
    # subsequent save replaces it cleanly.
    with open(state_file, "w") as f:
        f.write("{ broken json ")
    m = MechStateManager(state_file=state_file)
    assert m.load_state() == {}
    m.set_state("channel_overview_message_ids", {"333": {"overview": 9}})
    with open(state_file) as f:
        assert json.load(f)["channel_overview_message_ids"] == {"333": {"overview": 9}}

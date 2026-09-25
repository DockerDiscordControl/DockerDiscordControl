# -*- coding: utf-8 -*-
"""A state file that could not be read is not overwritten with almost nothing.

THE FINDING: when mech_state.json cannot be read - an I/O error on the mount,
a permission problem - load_state logs and returns {}, and the in-memory
cache stays empty. The file itself is untouched and still good. But the next
setter (an expand button, a Glvl change, a tracked overview id) writes that
empty cache plus its one key over the file: the tracked overview message ids
are gone, so the next restart posts duplicates, and every channel's mech
state with them. The docstring names exactly that loss - and then the code
causes it.

A write after a failed read tries the read once more. If it works, the change
lands on the real state; if it does not, the write is refused and said so.

Only an OSError counts: invalid JSON is unusable content, and replacing that
cleanly is the documented behaviour of this class.

COUNTER-CHECK (2026-09-22): red before - one setter after a failed read left
a file with a single key. The counter-checks keep ordinary saves, a fresh
install and the corrupt-file recovery working
(tests/unit/services/mech/test_mech_state_manager_atomic.py).
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from services.mech.mech_state_manager import MechStateManager

GOOD = {"channel_overview_message_ids": {"1": 11}, "last_glvl_per_channel": {"1": 5}}


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    path = tmp_path / "mech_state.json"
    path.write_text(json.dumps(GOOD), encoding="utf-8")
    return path


def _manager_that_could_not_read(state_file):
    with patch("builtins.open", side_effect=OSError("input/output error")):
        manager = MechStateManager()
        manager.load_state()
    return manager


def test_a_setter_after_a_failed_read_does_not_wipe_the_file(state_file):
    manager = _manager_that_could_not_read(state_file)

    with patch("builtins.open", side_effect=OSError("input/output error")):
        manager.set_last_glvl("1", 4)             # the read still fails

    assert json.loads(state_file.read_text(encoding="utf-8")) == GOOD, (
        "a transient read error cost the tracked message ids and every channel's state")


def test_a_read_that_works_again_keeps_the_old_state_and_adds_the_change(state_file):
    manager = _manager_that_could_not_read(state_file)

    manager.set_last_glvl("1", 4)                 # the file is readable again

    stored = json.loads(state_file.read_text(encoding="utf-8"))
    assert stored["channel_overview_message_ids"] == {"1": 11}, stored
    assert stored["last_glvl_per_channel"] == {"1": 4}


def test_an_ordinary_save_still_works(state_file):
    """Counter-check: nothing changes when the file can be read."""
    manager = MechStateManager()
    manager.load_state()

    manager.set_last_glvl("2", 7)

    stored = json.loads(state_file.read_text(encoding="utf-8"))
    assert stored["last_glvl_per_channel"] == {"1": 5, "2": 7}


def test_a_corrupt_file_is_still_replaced(state_file):
    """Counter-check: unusable content is not the same as an unreadable file."""
    state_file.write_text("{ broken json ", encoding="utf-8")
    manager = MechStateManager()
    assert manager.load_state() == {}

    manager.set_state("channel_overview_message_ids", {"3": 9})

    assert json.loads(state_file.read_text(encoding="utf-8")) == {
        "channel_overview_message_ids": {"3": 9}}


def test_a_fresh_install_still_writes(tmp_path, monkeypatch):
    """Counter-check: no file yet is not a read error."""
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    manager = MechStateManager()
    manager.load_state()

    manager.set_state("mech_id", "main")

    assert json.loads((tmp_path / "mech_state.json").read_text(encoding="utf-8")) == {"mech_id": "main"}

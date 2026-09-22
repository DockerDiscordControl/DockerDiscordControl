# -*- coding: utf-8 -*-
"""
THE FINDING (review C29, section 20 F1): `_atomic_update` promises, in its own
docstring,

    All writers (the bot's per-key _set/note_offline AND the web process's
    manual re-test) go through this, so neither ever overwrites verdicts owned
    by the other.

It does not keep that promise. The function reads the whole file, mutates one
key in memory and writes the whole file back, with nothing serialising the two
processes. If both reads happen before either write - the bot probing one
container while the web process handles a manual re-test for another - the
second write replaces the file with a state that never saw the first one's key.
A manual re-test that just proved a container supported can lose its verdict to
the bot's next probe, and the checkbox in the panel stays locked until the bot
happens to re-probe that container on its own schedule.

The reviewer could not tell from the section whether something else in the
project serialises these writers. Nothing does: there is no flock, no lock file
and no single-owner queue anywhere in the tree.

Two things were wrong, not one. The temp file was `query_support.tmp`, a FIXED
name shared by every writer, so two concurrent writes could also tear a single
key update. It carries the process id now.

The counter-check (test_a_single_write_leaves_no_litter) keeps the writing
itself clean.
"""

import json
import threading
import time
from pathlib import Path

import pytest

from services.infrastructure import game_query_support_service as support


@pytest.fixture
def verdicts_file(tmp_path, monkeypatch):
    monkeypatch.setattr(support, "_config_dir", lambda: tmp_path)
    return tmp_path / "query_support.json"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_slow_writer_does_not_lose_the_other_ones_verdict(verdicts_file):
    """THE FINDING: both writers keep their key, whoever finishes last."""
    def _slow(state):
        time.sleep(0.25)          # the window between read and write
        state["slow-container"] = {"supported": True, "final": True}

    def _quick(state):
        state["quick-container"] = {"supported": False, "final": False}

    slow = threading.Thread(target=support._atomic_update, args=(_slow,))
    slow.start()
    time.sleep(0.05)              # the quick writer arrives inside that window
    support._atomic_update(_quick)
    slow.join(timeout=5)

    state = _read(verdicts_file)
    assert sorted(state) == ["quick-container", "slow-container"], state


def test_many_writers_all_arrive(verdicts_file):
    """The same thing at scale: eight writers, eight keys, valid JSON."""
    def _writer(index):
        def _m(state):
            time.sleep(0.02)
            state[f"c{index}"] = {"supported": True}
        support._atomic_update(_m)

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    state = _read(verdicts_file)
    assert sorted(state) == sorted(f"c{i}" for i in range(8)), state


def test_a_single_write_leaves_no_litter(verdicts_file, tmp_path):
    """COUNTER-CHECK: the ordinary write still works and cleans up after
    itself - no half-written temp file left in the config directory."""
    support.record_manual_success("web", protocol="a2s", port=27015)

    assert _read(verdicts_file)["web"]["supported"] is True
    assert list(tmp_path.glob("*.tmp*")) == []

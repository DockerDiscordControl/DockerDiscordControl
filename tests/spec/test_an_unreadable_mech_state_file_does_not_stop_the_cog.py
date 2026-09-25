# -*- coding: utf-8 -*-
"""A mech state file nobody can read must not take Docker control down with it.

THE FINDING (review E21, cogs/docker_control.py ``__init__``): the cog's
construction opens with

    logger.debug("Step 1: Loading mech state...")
    try:
        state_data = self.mech_state_manager.load_state()
    except Exception as e:
        logger.error(f"[DEBUG INIT] Step 1 FAILED: {e}", exc_info=True)
        raise

and ``raise`` there is right for a constructor - a half-built cog is worse than
none. The problem is one level down. ``MechStateManager.load_state`` catches
``(FileNotFoundError, json.JSONDecodeError)`` and returns ``{}``, which handles
a missing file and a corrupt one. It does not handle a file that exists, is
valid, and **cannot be opened**.

``PermissionError`` is an ``OSError``, not a ``FileNotFoundError``. So it
escapes, Step 1 re-raises, the cog is never constructed, the extension fails to
load - and DDC has no container commands at all. Every start, until somebody
works out that a JSON file holding which mech panels were expanded is the
reason ``/serverstatus`` no longer exists.

**This is not hypothetical on this install.** Files written by a root-owned
process have broken this app before; it is why every `docker exec` here runs
`-u ddc`.

What the persisted state buys is real and it is not container control: mech
expand states, Glvl tracking, and the overview message ids that let a restart
delete an old overview instead of posting a duplicate. Losing those is a bad
morning. Losing Docker control is a broken bot. So the file is read
defensively, and a failure that is NOT simply "no file yet" is logged at ERROR,
because that one an operator can actually fix.
"""

import json
import logging

import pytest


@pytest.fixture
def manager(tmp_path):
    from services.mech.mech_state_manager import MechStateManager

    instance = MechStateManager.__new__(MechStateManager)
    instance.state_file = str(tmp_path / "mech_state.json")
    instance.state_cache = {}
    return instance


def test_an_unreadable_file_does_not_raise(manager, monkeypatch, caplog):
    def denied(*_a, **_kw):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", denied)

    with caplog.at_level(logging.DEBUG):
        state = manager.load_state()

    assert state == {}, "a file that could not be read must read as no state"


def test_an_unreadable_file_says_so_at_error(manager, monkeypatch, caplog):
    """A missing file is normal. A file you are not allowed to open is not."""
    def denied(*_a, **_kw):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", denied)

    with caplog.at_level(logging.DEBUG):
        manager.load_state()

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, (
        "the persisted state was silently dropped at WARNING level; an operator "
        "who can fix the permissions is never told there is anything to fix"
    )
    assert "Permission" in " ".join(errors), (
        f"the reason was not named, so nobody knows what to fix: {errors!r}"
    )


def test_a_missing_file_is_still_quiet(manager, caplog):
    """Counter-check: first start has no file, and that is not an error."""
    with caplog.at_level(logging.DEBUG):
        state = manager.load_state()

    assert state == {}
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "a first start with no state file was reported as an error"
    )


def test_a_readable_file_is_still_read(manager):
    """Counter-check: the defence must not swallow the normal case."""
    with open(manager.state_file, "w") as handle:
        json.dump({"last_glvl_per_channel": {"111": 7}}, handle)

    assert manager.load_state() == {"last_glvl_per_channel": {"111": 7}}

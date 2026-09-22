# -*- coding: utf-8 -*-
"""The one poster nobody calls is gone, not waiting to be wired back up.

THE FINDING: _update_all_overview_messages_after_donation deleted and
reposted every channel's overview with no per-channel lock at all around
delete -> send -> track, and it swept the channel with the unfiltered clean
sweep that takes Live Logs and auto-action notices with it. It is unreachable
today - the donation event goes through _auto_update_ss_messages instead, and
docker_control.py says so - so the only thing it could ever do was duplicate
messages on the day somebody wired it back up. 165 lines of it.

The donation path keeps working through the method that has the lock.

COUNTER-CHECK (2026-09-22): the file's own test suite stays green with it
removed, which is what "unreachable" means here; the donation test below is
the path that really runs.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COG = (ROOT / "cogs" / "message_updates.py").read_text(encoding="utf-8")
CONTROL = (ROOT / "cogs" / "docker_control.py").read_text(encoding="utf-8")


def test_the_unreachable_poster_is_gone():
    assert "_update_all_overview_messages_after_donation" not in COG


def test_nothing_refers_to_it_any_more():
    for path in (ROOT / "cogs").glob("*.py"):
        assert "_update_all_overview_messages_after_donation" not in path.read_text(encoding="utf-8"), path


def test_the_donation_event_still_updates_the_overviews():
    """Counter-check: the path that really runs is untouched."""
    block = CONTROL[CONTROL.index("Discord update event received"):]
    assert "_auto_update_ss_messages" in block[:800]

# -*- coding: utf-8 -*-
"""No private panel waits longer than ten minutes, and every one can be deleted.

THE FINDING (operator's question, 2026-10-02): Discord lets DDC delete a
private (ephemeral) message only within fifteen minutes of the answer that
made it. Some private panels could not be deleted in that time at all:
- the mech details, mech selection and mech story panels had no timeout -
  they stayed until dismissed by hand;
- the /info panel for protected info waited 30 minutes, past the token;
- the private donation panel deleted itself through message.delete(), which
  for an ephemeral message is the channel route - a 404 - and bypassed the
  shared deletion path.

THE CONTRACT: a private panel closes after at most MAX_PRIVATE_SECONDS (ten
minutes) without use; the ones that had none get PRIVATE_PANEL_SECONDS (five
minutes). The private donation panel goes the shared way (DDCView.on_timeout,
fresh token). The mech details view keeps timeout=None only where it is
registered as a persistent view at start, which Discord requires.

HOW THIS TEST CAN FAIL: a private panel class without a timeout or above ten
minutes comes back, or the donation panel deletes by the channel route again.

COUNTER-CHECK (2026-10-02): red before the change (None, None, None, 1800,
890 and the 404 route).
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from cogs.ddc_ui import MAX_PRIVATE_SECONDS, PRIVATE_PANEL_SECONDS

PROJECT = Path(__file__).resolve().parents[2]


def test_the_limits():
    assert (PRIVATE_PANEL_SECONDS, MAX_PRIVATE_SECONDS) == (300, 600)


@pytest.mark.asyncio
async def test_the_panels_that_had_none():
    from cogs.mech_ui import MechDetailsView, MechSelectionView, MechStoryView
    cog = SimpleNamespace()
    assert MechDetailsView(cog, 1).timeout == PRIVATE_PANEL_SECONDS
    assert MechDetailsView(cog, 1, timeout=None).timeout is None, "the persistent registration"
    assert MechSelectionView(cog, 1).timeout == PRIVATE_PANEL_SECONDS
    assert MechStoryView(cog, 1).timeout == PRIVATE_PANEL_SECONDS


def test_every_private_panel_class_stays_within_ten_minutes():
    """Each PrivateView subclass gives its timeout as a bound name or a number up to 600."""
    allowed_names = {"PRIVATE_PANEL_SECONDS", "MAX_PRIVATE_SECONDS", "timeout"}
    found = []
    for path in sorted((PROJECT / "cogs").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"^class (\w+)\(PrivateView\):", text, re.M):
            body = text[match.end():]
            following = re.search(r"^class ", body, re.M)
            body = body[:following.start()] if following else body
            call = re.search(r"super\(\)\.__init__\(timeout=([\w.]+)\)", body)
            value = call.group(1) if call else "?"
            fine = value in allowed_names or (value.isdigit() and int(value) <= 600)
            if not fine:
                found.append(f"{path.name}:{match.group(1)} timeout={value}")
    assert found == [], found


@pytest.mark.asyncio
async def test_the_private_donation_panel_goes_the_shared_way(monkeypatch):
    from cogs.ddc_ui import DDCView
    from cogs.donation_ui import DonationView
    shared = []

    async def on_timeout(self):
        shared.append(type(self).__name__)
    monkeypatch.setattr(DDCView, "on_timeout", on_timeout)

    private = DonationView(True, private=True)
    assert private.timeout == MAX_PRIVATE_SECONDS
    await private.on_timeout()
    assert shared == ["DonationView"]

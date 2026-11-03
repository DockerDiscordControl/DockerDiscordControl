# -*- coding: utf-8 -*-
"""A private panel sent as a followup is noted as itself, not as the message it answers.

THE FINDING (py-cord 2.6.1 -> 2.8.1, 2026-11-03): py-cord 2.8.1's followup
send sets view.message to the new followup message and right after that
view.parent to the interaction behind it (discord/webhook/async_.py,
Webhook.send: ``view.message = ...`` then ``if self.parent and not
view.parent: view.parent = self.parent``). 2.6.1 never set parent on a
followup. DDCView's parent setter noted "@original" of that interaction,
overwriting the exact note the message setter had just written. For a press
answered with defer() (cogs/admin_ui.py: defer, then a followup with
AdminContainerSelectView) "@original" is the PUBLIC message the button sits
on - so a restart within fifteen minutes deleted the public admin overview.

THE CONTRACT: once a panel is noted by its own message, a parent arriving
afterwards does not change the note. A panel sent as the answer (parent
alone, or parent before message, as py-cord does for send_message) is still
noted as "@original" (test_a_restart_takes_the_open_private_panels_away).

HOW THIS TEST CAN FAIL: the parent setter notes "@original" although the
message setter already noted the followup.

COUNTER-CHECK (2026-11-03): red before the fix (target "@original", token
"press-token"); red again with the fix's guard removed.
"""

import json
from types import SimpleNamespace

import pytest

import services.discord.private_panels as panels
from cogs.ddc_ui import PrivateView

T0 = 1_000_000.0


class _Panel(PrivateView):
    def __init__(self):
        super().__init__(timeout=300)


@pytest.fixture
def notes(tmp_path, monkeypatch):
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(panels.time, "time", lambda: T0)

    def read():
        path = tmp_path / "private_panels.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return read


def _followup_message(message_id, token):
    """A followup as py-cord builds it: its state carries the interaction webhook."""
    return SimpleNamespace(id=message_id, flags=SimpleNamespace(ephemeral=True),
                           _state=SimpleNamespace(_webhook=SimpleNamespace(id=42, token=token)))


@pytest.mark.asyncio
async def test_a_followup_keeps_its_own_note_when_py_cord_sets_the_parent_after_it(notes):
    view = _Panel()
    # The order of py-cord 2.8.1's Webhook.send.
    view.message = _followup_message(77, "followup-token")
    view.parent = SimpleNamespace(application_id=42, token="press-token")

    note = notes()[view.id]
    assert note["target"] == "77", f"the panel is noted as the message it answers: {note}"
    assert note["token"] == "followup-token"


@pytest.mark.asyncio
async def test_an_answer_with_parent_first_is_still_noted_as_the_original(notes):
    view = _Panel()
    # The order of py-cord 2.8.1's send_message: parent, then the original response.
    view.parent = SimpleNamespace(application_id=42, token="answer-token")
    original = SimpleNamespace(id=55, flags=SimpleNamespace(ephemeral=True),
                               _state=SimpleNamespace(_interaction=SimpleNamespace(
                                   application_id=42, token="answer-token")))
    view.message = original

    note = notes()[view.id]
    assert note["target"] == "@original"
    assert note["token"] == "answer-token"

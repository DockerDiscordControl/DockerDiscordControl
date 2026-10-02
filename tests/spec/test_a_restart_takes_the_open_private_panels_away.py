# -*- coding: utf-8 -*-
"""Private panels that were open when DDC restarted are deleted when it starts.

THE OPERATOR (2026-10-02): private panels must go reliably. A view's timeout
lives in memory; a restart (a rebuild takes 60 to 90 seconds) lost every
timer, and the panels stayed until each person dismissed them by hand.
Discord allows deleting them for fifteen minutes through the token of the
interaction behind them, so that token is written down while the panel is
open, and the start of DDC deletes every panel whose token still works.

THE CONTRACT:
- a private panel is noted however it went out: as a followup (its webhook
  message), as the answer itself (view.parent), and renewed by a press that
  answered on it (a fresh token);
- a panel that timed out and was deleted is forgotten;
- the start deletes the noted panels whose fifteen minutes still run, not
  the others, and clears the notes.

HOW THIS TEST CAN FAIL: a way of sending is not noted, a press does not
renew the token, or the start deletes an expired one or keeps the notes.

COUNTER-CHECK (2026-10-02): red with the notes taken out of DDCView (nothing
noted) and with the start not clearing the file.
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
    clock = [T0]
    monkeypatch.setattr(panels.time, "time", lambda: clock[0])

    def read():
        path = tmp_path / "private_panels.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return read, clock


def _webhook_message(message_id, token):
    """A followup as py-cord builds it: its state carries the interaction webhook."""
    return SimpleNamespace(id=message_id, flags=SimpleNamespace(ephemeral=True),
                           _state=SimpleNamespace(_webhook=SimpleNamespace(id=42, token=token)))


@pytest.mark.asyncio
async def test_a_followup_panel_is_noted(notes):
    read, clock = notes
    view = _Panel()
    view.message = _webhook_message(77, "followup-token")
    assert read()[view.id] == {"application_id": "42", "token": "followup-token", "target": "77",
                               "until": T0 + 900}


@pytest.mark.asyncio
async def test_an_answer_panel_is_noted(notes):
    read, clock = notes
    view = _Panel()
    view.parent = SimpleNamespace(application_id=42, token="answer-token")
    assert read()[view.id]["token"] == "answer-token"
    assert read()[view.id]["target"] == "@original"


@pytest.mark.asyncio
async def test_a_press_renews_the_token(notes):
    read, clock = notes
    view = _Panel()
    view.parent = SimpleNamespace(application_id=42, token="answer-token")
    clock[0] += 600

    async def original_response():
        return SimpleNamespace(id=55)
    press = SimpleNamespace(message=SimpleNamespace(id=55, flags=SimpleNamespace(ephemeral=True)),
                            original_response=original_response, application_id=42, token="press-token")
    await view._remember_a_deleter(press)
    assert read()[view.id]["token"] == "press-token"
    assert read()[view.id]["until"] == T0 + 600 + 900


@pytest.mark.asyncio
async def test_a_timed_out_panel_is_forgotten(notes):
    read, clock = notes
    view = _Panel()

    async def delete_original_response():
        return None
    view.parent = SimpleNamespace(application_id=42, token="answer-token",
                                  delete_original_response=delete_original_response)
    await view.on_timeout()
    assert view.id not in read()


@pytest.mark.asyncio
async def test_the_start_deletes_what_it_still_may(notes):
    read, clock = notes
    panels.remember("a", 42, "fresh", "@original")
    clock[0] += 600
    panels.remember("b", 42, "younger", "88")
    clock[0] += 400                          # "a" is 1000 s old - its token died at 900
    asked = []

    async def delete(record):
        asked.append(record["token"])
        return 204
    assert await panels.delete_left_behind(delete=delete) == 1
    assert asked == ["younger"]
    assert read() == {}, "the notes were kept"


def test_the_start_runs_it():
    from app.bot.startup_steps import STARTUP_STEPS, remove_left_private_panels_step
    assert remove_left_private_panels_step in STARTUP_STEPS

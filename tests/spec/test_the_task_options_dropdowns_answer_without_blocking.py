# -*- coding: utf-8 -*-
"""The wait/warning dropdowns under a new task answer in time and always answer.

THE FINDING (second review before v3.1.0, 2026-09-29; review of the Discord
paths and stage 4 section 49). cogs/task_player_options._answer ran _save -
find the task, update_task under the tasks lock, query the player count - on
the bot's event loop, before its first response. tasks.json often lives on a
network mount, and the scheduler's rule B8 is that its I/O goes off the loop:
a lock held by another writer stalled the whole bot and could miss Discord's
3 seconds. And only the errors _save returns were answered; an exception
out of it (the player-count query reaches other services) left the member
with "This interaction failed" while the choice may already have been saved.

THE CONTRACT: _answer acknowledges first, runs _save in a worker thread, and
an exception from it is answered in Discord and logged.

HOW THIS TEST CAN FAIL: _save runs on the loop again, before the answer, or
an exception out of it goes unanswered.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cogs import task_player_options as options


def _interaction(order):
    interaction = MagicMock()
    interaction.response.defer = AsyncMock(side_effect=lambda *a, **k: order.append("defer"))
    interaction.response.send_message = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=True)
    interaction.followup.send = AsyncMock()
    return interaction


@pytest.mark.asyncio
async def test_the_save_runs_after_the_answer_and_off_the_loop(monkeypatch):
    order, threads = [], []
    loop_thread = threading.get_ident()
    monkeypatch.setattr(options, "_may_edit", lambda *_a: True)

    def _save(task_id, change):
        order.append("save")
        threads.append(threading.get_ident())
        return SimpleNamespace(options={}), None, []

    monkeypatch.setattr(options, "_save", _save)
    interaction = _interaction(order)

    await options._answer(interaction, "t1", "Icarus", {"warn_minutes": 5})

    assert order == ["defer", "save"], order
    assert threads and threads[0] != loop_thread, "tasks.json was written on the bot's loop"
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_exception_while_saving_is_answered(monkeypatch):
    monkeypatch.setattr(options, "_may_edit", lambda *_a: True)

    def _save(task_id, change):
        raise KeyError("player count service")

    monkeypatch.setattr(options, "_save", _save)
    interaction = _interaction([])

    await options._answer(interaction, "t1", "Icarus", {"warn_minutes": 5})

    interaction.followup.send.assert_awaited_once()
    assert "❌" in interaction.followup.send.await_args.args[0]


@pytest.mark.asyncio
async def test_a_refused_channel_is_answered_before_anything_is_saved(monkeypatch):
    """Counter-check: the permission refusal still comes first and saves nothing."""
    monkeypatch.setattr(options, "_may_edit", lambda *_a: False)
    saved = []
    monkeypatch.setattr(options, "_save", lambda *a: saved.append(a))
    interaction = _interaction([])

    await options._answer(interaction, "t1", "Icarus", {"warn_minutes": 5})

    assert not saved
    interaction.response.send_message.assert_awaited_once()

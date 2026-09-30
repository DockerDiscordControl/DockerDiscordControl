# -*- coding: utf-8 -*-
"""The task delete panel says how many tasks it shows, and counts active ones as active.

THE FINDING (stage 4 review before v3.1.0, section 41 pass 4): with more
than 25 tasks for one container the delete panel said "N active tasks"
with the full count, and its view was meant to show the first 25 (Discord's
limit) - but PrivateView appends its ✕, a 26th item, so from 25 tasks on
the view could not be built at all and the panel only said "Error opening
task delete panel" (found while writing this test). The count also called
inactive tasks "active".

THE CONTRACT: the panel opens with the first 24 tasks and the ✕; the
active count counts active tasks; beyond 24 a footer says how many of how
many are shown.

HOW THIS TEST CAN FAIL: the cut is silent again, or inactive tasks are
counted as active.

COUNTER-CHECK (2026-09-30): red before the change (no panel at all).
"""

from types import SimpleNamespace

import pytest

import cogs.translation_manager as translation_manager
from cogs.ddc_ui import CloseButton
from cogs.task_ui import DeleteTasksButton
from services.scheduling.scheduled_task import ScheduledTask


def _tasks(count, inactive):
    tasks = []
    for i in range(count):
        task = ScheduledTask(container_name="x", action="stop", cycle="daily",
                             hour=i % 24, minute=0, timezone_str="UTC")
        task.is_active = i >= inactive
        tasks.append(task)
    return tasks


@pytest.mark.asyncio
async def test_27_tasks_say_what_is_shown(monkeypatch):
    monkeypatch.setattr(translation_manager.translation_manager, "get_current_language", lambda: "en")
    monkeypatch.setattr("services.scheduling.scheduler.get_tasks_for_container",
                        lambda name: _tasks(27, inactive=2))
    sent = []

    async def defer(**kwargs):
        return None

    async def send(*args, **kwargs):
        sent.append(kwargs)
    interaction = SimpleNamespace(response=SimpleNamespace(defer=defer),
                                  followup=SimpleNamespace(send=send))

    await DeleteTasksButton(None, "x").callback(interaction)

    embed, view = sent[0]["embed"], sent[0]["view"]
    assert len(view.children) == 25, "24 tasks and the ✕"
    assert isinstance(view.children[-1], CloseButton)
    found = [field.value for field in embed.fields if field.name == "Found Tasks"][0]
    assert found.startswith("25 active tasks"), found
    assert embed.footer.text == "Showing first 24 of 27 tasks"

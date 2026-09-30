# -*- coding: utf-8 -*-
"""A delete press on a task that is already gone says so, not "no permission".

THE FINDING (stage 4 review before v3.1.0, section 41 pass 4): for an
admin assigned to containers, in a channel without 'schedule', pressing a
delete button whose task had been deleted elsewhere answered "You do not
have permission to delete tasks in this channel" - the permission check
asks for the task's container, and a task that is gone has none. The
truth is "Task not found".

THE CONTRACT: a task that is gone is answered as gone, before the
permission check; an existing task still meets the check first.

HOW THIS TEST CAN FAIL: the permission text comes back for a missing task,
or a missing permission is skipped for an existing one.

COUNTER-CHECK (2026-09-30): red before the change (the permission text).
"""

from types import SimpleNamespace

import pytest

import cogs.control_helpers as control_helpers
import cogs.translation_manager as translation_manager
from cogs.task_ui import ContainerTaskDeleteButton


@pytest.fixture
def press(monkeypatch):
    monkeypatch.setattr(translation_manager.translation_manager, "get_current_language", lambda: "en")
    monkeypatch.setattr("cogs.task_ui.load_config", lambda: {})
    monkeypatch.setattr(control_helpers, "_channel_has_permission", lambda *a, **k: False)
    deleted = []
    monkeypatch.setattr("services.scheduling.scheduler.delete_task", lambda task_id: deleted.append(task_id))
    sent = []

    async def defer(**kwargs):
        return None

    async def send(text=None, **kwargs):
        sent.append(text)
    interaction = SimpleNamespace(response=SimpleNamespace(defer=defer), followup=SimpleNamespace(send=send),
                                  channel_id=111, user=SimpleNamespace(id=42))

    async def run(task, admin_may):
        monkeypatch.setattr("services.scheduling.scheduler.find_task_by_id", lambda task_id: task)
        monkeypatch.setattr(control_helpers, "_admin_may_control_task", lambda *a, **k: admin_may)
        await ContainerTaskDeleteButton(None, "gone-id", "D:10h", 0).callback(interaction)
        return sent[-1], deleted
    return run


@pytest.mark.asyncio
async def test_a_gone_task_is_called_gone(press):
    text, deleted = await press(None, admin_may=False)
    assert "Task not found" in text, text
    assert deleted == []


@pytest.mark.asyncio
async def test_an_existing_task_still_meets_the_permission_check(press):
    task = SimpleNamespace(container_name="x", cycle="daily", action="stop")
    text, deleted = await press(task, admin_may=False)
    assert "permission" in text, text
    assert deleted == []

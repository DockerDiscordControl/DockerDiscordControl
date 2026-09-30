# -*- coding: utf-8 -*-
"""Re-picking the cycle or the action takes the Create button's readiness back.

THE FINDING (stage 4 review before v3.1.0, section 41 pass 4): after a
task was complete (Create enabled), picking the cycle or the action again
reset the later selections but left Create enabled; pressing it answered
"Please select: Action, Time". Nothing wrong was created - the button
just claimed a readiness the form no longer had.

THE CONTRACT: every step that resets later selections asks again whether
the task is ready.

HOW THIS TEST CAN FAIL: Create stays enabled after a reset.

COUNTER-CHECK (2026-09-30): red before the change (enabled after the reset).
"""

from types import SimpleNamespace

import pytest

from cogs.task_ui import ActionDropdown, CycleDropdown, TaskCreationView, TimeDropdown


async def _pick(view, kind, value):
    select = next(item for item in view.children if isinstance(item, kind))
    select._interaction = object()
    select._selected_values = [value]

    async def edit_message(**kwargs):
        return None
    await select.callback(SimpleNamespace(response=SimpleNamespace(edit_message=edit_message)))


async def _complete_daily_stop():
    view = TaskCreationView(None, "x", allowed_actions=["stop"])
    await _pick(view, CycleDropdown, "daily")
    await _pick(view, ActionDropdown, "stop")
    await _pick(view, TimeDropdown, "10:00")
    assert view.create_button.disabled is False, "the flow did not complete - the test proves nothing"
    return view


@pytest.mark.asyncio
async def test_a_new_cycle_disables_create():
    view = await _complete_daily_stop()
    await _pick(view, CycleDropdown, "weekly")
    assert view.create_button.disabled is True


@pytest.mark.asyncio
async def test_a_new_action_disables_create():
    view = await _complete_daily_stop()
    await _pick(view, ActionDropdown, "stop")
    assert view.create_button.disabled is True

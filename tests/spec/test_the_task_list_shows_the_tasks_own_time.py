# -*- coding: utf-8 -*-
"""The Discord task list shows a task's times in the task's zone, and says which.

THE FINDING (stage 4 review before v3.1.0, section 41 pass 3 F3 + pass 4
F1, verified 2026-09-29). _show_task_list formatted next and last run with
datetime.fromtimestamp() - the PROCESS zone - and no zone name. The image
sets TZ=Europe/Berlin; the configured zone defaults to UTC. A task created
for 13:00 said "13:00 UTC" when it was created and on its delete button,
and "15:00" without a zone in the list, one click away.

THE CONTRACT: the list shows next and last run in the task's own zone
(timezone_str), with the zone's name - like the confirmation and the
delete buttons.

HOW THIS TEST CAN FAIL: the list formats in the process zone again.

It goes through TaskManagementButton._show_task_list and reads the embed
it sends.

COUNTER-CHECK (2026-09-29): written before the fix and red then.
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def berlin_process(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Berlin")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_the_list_shows_13_utc_not_15_berlin(berlin_process, monkeypatch):
    from services.scheduling import scheduler
    from cogs.task_ui import TaskManagementButton

    at = datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc).timestamp()
    task = scheduler.ScheduledTask(container_name="x", action="restart", cycle="daily",
                                   hour=13, minute=0, timezone_str="UTC")
    task.next_run_ts = at
    task.last_run_ts = at - 86400
    task.last_run_success = True
    monkeypatch.setattr(scheduler, "get_tasks_for_container", lambda name: [task])

    interaction = MagicMock()
    interaction.followup.send = AsyncMock()
    button = TaskManagementButton(MagicMock(), {"docker_name": "x"})
    asyncio.run(button._show_task_list(interaction))

    embed = interaction.followup.send.await_args.kwargs["embed"]
    value = embed.fields[0].value
    assert "13:00" in value and "15:00" not in value, value
    assert "UTC" in value, f"the list does not say which zone: {value}"

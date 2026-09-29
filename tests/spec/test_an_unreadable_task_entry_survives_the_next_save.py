# -*- coding: utf-8 -*-
"""A task entry that cannot be built is kept, not deleted by the next save.

THE FINDING (stage 4 review before v3.1.0, section 26 pass 4 F1): load_tasks
skipped an entry of tasks.json that ScheduledTask.from_dict could not build
(e.g. "schedule_details": null from a hand edit or another version), and the
read still counted as successful. The next save of ANYTHING - adding,
editing, a run's write-back - wrote tasks.json without it: the task was
deleted for good, with no backup and no message. Review E5 forbade exactly
that for tasks that fail is_valid(). A top-level object instead of a list
lost every entry the same way.

THE CONTRACT: an unreadable entry is not scheduled, is logged at ERROR, and
is written back unchanged by every save. A file that is not a list counts as
a failed read (saves are refused, as for broken JSON).

HOW THIS TEST CAN FAIL: the entry vanishes at the next save; or a file that
is an object is overwritten.

It goes through scheduler.add_task, the path the panel and Discord use.

COUNTER-CHECK (2026-09-29): both cases red before the change.
"""

import json

import pytest

from services.scheduling import runtime as scheduler_runtime
from services.scheduling import scheduler as scheduler_mod
from services.scheduling.scheduler import CYCLE_DAILY, ScheduledTask, add_task

BROKEN = {"id": "keepme", "container": "nginx", "action": "restart", "cycle": "daily",
          "schedule_details": None}


@pytest.fixture
def tasks_file(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [])
    fresh.ensure_layout()
    yield fresh.tasks_file_path
    scheduler_runtime.reset_scheduler_runtime()


def _task(task_id, container, hour):
    return ScheduledTask(task_id=task_id, container_name=container, action="restart",
                         cycle=CYCLE_DAILY, hour=hour, minute=0, timezone_str="UTC")


def test_an_entry_that_cannot_be_built_survives_an_add(tasks_file):
    tasks_file.write_text(json.dumps([_task("a", "web", 3).to_dict(), BROKEN]), encoding="utf-8")
    assert add_task(_task("b", "db", 5)) is True
    ids = [entry.get("id") for entry in json.loads(tasks_file.read_text(encoding="utf-8"))]
    assert "keepme" in ids, f"the unreadable entry was deleted by an unrelated add: {ids}"
    assert {"a", "b"} <= set(ids)


def test_a_file_that_is_no_list_is_not_overwritten(tasks_file):
    original = json.dumps({"keepme": BROKEN, "other": BROKEN})
    tasks_file.write_text(original, encoding="utf-8")
    assert add_task(_task("b", "db", 5)) is False
    assert tasks_file.read_text(encoding="utf-8") == original

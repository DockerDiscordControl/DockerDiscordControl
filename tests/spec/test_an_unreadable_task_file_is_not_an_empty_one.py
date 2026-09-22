# -*- coding: utf-8 -*-
"""A task file that could not be read is not a task file with no tasks in it.

THE FINDING (review E4, section 26 - never reviewed by either pass). This is
a data-loss path, and it needs three steps that are each unremarkable on their
own:

1. `load_tasks()` reads tasks.json itself and, on a JSONDecodeError or an IO
   error, LOGS and falls through with its list still empty. An unreadable file
   is indistinguishable from "there are no tasks".
2. Every writer starts from that list:

       tasks = load_tasks()      # [] after a failed read
       ...
       return save_tasks(tasks)  # writes the file from it

3. There is no backup. `_save_raw_tasks_to_file` replaces the file.

So: tasks.json is briefly unreadable - a half-written file, a permission
blip on the array, the retry loop in `_load_raw_tasks_from_file` exists
because IO errors happen here - the operator adds one task in the panel, and
every other task is gone. The only sign is an ERROR line nobody reads.

THE REPAIR is the narrow one: a read that failed is remembered, and writing
is refused while it stands, because every writer's list came from that read.
A successful read clears it, so a passing glitch heals itself.

What this deliberately does NOT do is guess. It does not keep a stale list
in memory and write that back, and it does not try to repair the file. It
refuses, says why, and leaves the file alone - the schedule on disk is the
only copy there is.
"""

import json

import pytest

import services.scheduling.runtime as scheduler_runtime
import services.scheduling.scheduler as scheduler_mod
from services.scheduling.scheduler import ScheduledTask

GOOD = [{"id": "keep-me", "container": "valheim", "action": "restart",
         "cycle": "daily", "hour": 4, "minute": 0, "active": True,
         "timezone": "Europe/Berlin"}]


@pytest.fixture
def tasks_file(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [])
    # Module state that outlives a test. Without this reset a corrupt-file case
    # poisons every later test in the same process - found by a probe that gave
    # three reds where two were announced.
    monkeypatch.setattr(scheduler_mod, "_last_load_failed", False)
    fresh.ensure_layout()
    path = fresh.tasks_file_path
    path.write_text(json.dumps(GOOD, indent=4), encoding="utf-8")
    yield path
    scheduler_runtime.reset_scheduler_runtime()


def _new_task():
    return ScheduledTask(container_name="nginx", action="start", cycle="daily",
                         hour=5, minute=0, timezone_str="Europe/Berlin")


def test_a_corrupt_file_is_not_overwritten_by_the_next_add(tasks_file):
    """The finding, end to end: the schedule must survive a bad read."""
    tasks_file.write_text("{ this is not json", encoding="utf-8")

    added = scheduler_mod.add_task(_new_task())

    assert added is False, "a task was added on top of a file nobody could read"
    assert tasks_file.read_text(encoding="utf-8") == "{ this is not json", (
        "the unreadable file was replaced - whatever was in it is now gone, "
        "and it was the only copy"
    )


@pytest.mark.parametrize("writer", ["delete", "update"])
def test_the_other_two_writers_are_safe_by_accident(tasks_file, writer):
    """Pinned BECAUSE it is an accident, not a design.

    delete_task and update_task both look their task up in the list they got
    back, do not find it in an empty one, and refuse before saving. That is
    luck, not care: it depends on them searching by id first. Written down so
    that a refactor which saves before searching is noticed.
    """
    tasks_file.write_text("[{\"id\": ", encoding="utf-8")

    if writer == "delete":
        result = scheduler_mod.delete_task("keep-me")
    else:
        task = _new_task()
        task.task_id = "keep-me"
        result = scheduler_mod.update_task(task)

    assert result is False
    assert tasks_file.read_text(encoding="utf-8") == "[{\"id\": "


def test_a_read_that_works_again_lets_writing_through(tasks_file):
    """A passing glitch heals itself - this must not be a one-way door."""
    tasks_file.write_text("{ this is not json", encoding="utf-8")
    scheduler_mod.load_tasks()                     # the failed read
    tasks_file.write_text(json.dumps(GOOD, indent=4), encoding="utf-8")

    assert scheduler_mod.add_task(_new_task()) is True, (
        "the file is readable again and writing is still refused"
    )
    stored = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert {t["id"] for t in stored} == {"keep-me", _new_task().task_id} - {None} or len(stored) == 2, stored


def test_an_ordinary_save_still_works(tasks_file):
    """The counter-case: none of this may be bought with a scheduler that cannot write."""
    assert scheduler_mod.add_task(_new_task()) is True

    stored = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert len(stored) == 2, stored


def test_an_empty_file_is_still_simply_empty(tasks_file):
    """A file that says "[]" is not a failure - it is a schedule with nothing in it."""
    tasks_file.write_text("[]", encoding="utf-8")

    assert scheduler_mod.add_task(_new_task()) is True
    assert len(json.loads(tasks_file.read_text(encoding="utf-8"))) == 1

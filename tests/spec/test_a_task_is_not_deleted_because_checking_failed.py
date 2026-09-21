# -*- coding: utf-8 -*-
"""A task whose validity could not be determined is kept, not deleted.

THE FINDING (review E5, section 26 - never reviewed by either pass).
`ScheduledTask.is_valid()` ends with

    except (ValueError, TypeError, AttributeError) as e:
        logger.error(f"Data error validating task {self.task_id}: {e}")
        return False

so an error WHILE CHECKING counts as "invalid". And `load_tasks()` acts on
that answer by deleting:

    valid_tasks = [task for task in tasks if task.is_valid()]
    if len(valid_tasks) != len(tasks):
        ... save_tasks(valid_tasks)      # the others are gone from tasks.json

One boolean drives two very different consequences. `add_task` and
`update_task` also ask `is_valid()`, and there "could not tell -> refuse" is
exactly right: nothing is lost by refusing. The cleanup is not symmetrical -
it removes the task from the operator's schedule for good, and there is no
backup.

So the rule this pins is: **a check that could not be made is not a verdict.**
A task that is definitely invalid is still removed - that is what the cleanup
is for - but one whose validation fell over stays, and says so in the log.

Not hypothetical in kind: this is the same shape as C33, D20 and D25, where a
narrow handler met a DDC exception. Here the meeting point is any unexpected
data shape inside a cycle validator, and the cost is the highest in this file.
"""

import json

import pytest

import services.scheduling.runtime as scheduler_runtime
import services.scheduling.scheduler as scheduler_mod
from services.scheduling.scheduler import ScheduledTask

KEEP = {"id": "monthly-one", "container": "valheim", "action": "restart",
        "cycle": "monthly", "day": 1, "hour": 4, "minute": 0, "active": True,
        "timezone": "Europe/Berlin"}
JUNK = {"id": "junk-one", "container": "nginx", "action": "restart",
        "cycle": "fortnightly", "hour": 4, "minute": 0, "active": True,
        "timezone": "Europe/Berlin"}


@pytest.fixture
def tasks_file(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [])
    monkeypatch.setattr(scheduler_mod, "_last_load_failed", False)
    monkeypatch.setattr(scheduler_mod, "_failed_cleanup_ids", frozenset())
    fresh.ensure_layout()
    yield fresh.tasks_file_path
    scheduler_runtime.reset_scheduler_runtime()


def _stored(path):
    return {entry["id"] for entry in json.loads(path.read_text(encoding="utf-8"))}


def _validation_explodes(monkeypatch):
    def _boom(self):
        raise TypeError("'<' not supported between instances of 'str' and 'int'")

    monkeypatch.setattr(ScheduledTask, "_validate_monthly", _boom)


def test_a_task_whose_check_fell_over_stays_in_the_file(tasks_file, monkeypatch):
    """The finding: an error while checking is not a verdict."""
    tasks_file.write_text(json.dumps([KEEP], indent=4), encoding="utf-8")
    _validation_explodes(monkeypatch)

    scheduler_mod.load_tasks()

    assert _stored(tasks_file) == {"monthly-one"}, (
        "the task was deleted from the schedule because validating it raised - "
        "there is no backup and nothing asked the operator"
    )


def test_it_is_also_still_handed_out(tasks_file, monkeypatch):
    """Kept in the file AND kept in the list, or the scheduler forgets it anyway."""
    tasks_file.write_text(json.dumps([KEEP], indent=4), encoding="utf-8")
    _validation_explodes(monkeypatch)

    tasks = scheduler_mod.load_tasks()

    assert [task.task_id for task in tasks] == ["monthly-one"]


def test_a_task_that_really_is_invalid_is_still_removed(tasks_file):
    """The counter-case: the cleanup must keep doing its job."""
    tasks_file.write_text(json.dumps([KEEP, JUNK], indent=4), encoding="utf-8")

    scheduler_mod.load_tasks()

    assert _stored(tasks_file) == {"monthly-one"}, (
        "an unknown cycle is a real defect and the cleanup exists to remove it"
    )


def test_a_healthy_file_is_left_alone(tasks_file):
    """A pin: no cleanup, no rewrite."""
    tasks_file.write_text(json.dumps([KEEP], indent=4), encoding="utf-8")
    before = tasks_file.read_text(encoding="utf-8")

    scheduler_mod.load_tasks()

    assert tasks_file.read_text(encoding="utf-8") == before

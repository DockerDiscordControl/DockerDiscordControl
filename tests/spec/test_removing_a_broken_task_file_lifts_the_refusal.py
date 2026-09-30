# -*- coding: utf-8 -*-
"""Removing a broken tasks.json lifts the save refusal at once.

THE FINDING (stage 4 review before v3.1.0, section 26 pass 4 F3): after a
failed read every save is refused, and the refusal says "Fix or remove the
file; the next successful read lifts this by itself". But when the file was
missing, load_tasks created "[]" and returned early - without clearing the
failed-read flag, so the operator's removal still failed the next save.
The same early return left out the system tasks (the donation task) and
the cache on the first load after a fresh install.

THE CONTRACT: a created empty file is a successful read like any other:
the flag is cleared, the cache replaced and the system tasks added.

HOW THIS TEST CAN FAIL: the save after the removal is refused again, or a
fresh install's first load lacks the system tasks.

COUNTER-CHECK (2026-09-30): red before the change (add_task False; no
system task).
"""

import json

import services.scheduling.scheduler as scheduler_mod
from tests.spec.test_an_unreadable_task_file_is_not_an_empty_one import _new_task, tasks_file  # noqa: F401


def test_the_first_save_after_the_removal_works(tasks_file):  # noqa: F811
    tasks_file.write_text("{broken", encoding="utf-8")
    scheduler_mod.load_tasks()
    tasks_file.unlink()                      # what the refusal tells the operator to do

    assert scheduler_mod.add_task(_new_task()) is True
    saved = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert [entry.get("container") for entry in saved] == ["nginx"]


def test_a_fresh_install_loads_its_system_tasks(tasks_file, monkeypatch):  # noqa: F811
    system_task = _new_task()
    monkeypatch.setattr(scheduler_mod, "_get_system_tasks", lambda: [system_task])
    tasks_file.unlink()

    assert system_task in scheduler_mod.load_tasks()

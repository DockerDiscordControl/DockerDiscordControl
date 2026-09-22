# -*- coding: utf-8 -*-
"""A task the panel deactivates is only called saved when it was.

THE FINDING: while listing tasks, the panel deactivates one-time tasks whose
time has passed and writes them back through _save_updated_tasks. update_task
returns a bool - it refuses a system task, an invalid one, or a recurring one
without a next run, and it returns False when the file could not be written -
and the caller threw that away, logging "Changes saved." every time. SPEC.md
Z3: no success is reported that did not happen. The list then showed the task
as deactivated while the file still held it as active, so it came back on the
next page load - and the scheduler still had it.

COUNTER-CHECK (2026-09-23): red before - "Changes saved." for a refused write,
and no error anywhere. test_a_saved_task_is_reported_as_saved holds the other
side: reporting every write as failed would be green without it.
"""

import logging
from types import SimpleNamespace

import pytest

from services.web.task_management_service import TaskManagementService


@pytest.fixture
def task():
    return SimpleNamespace(task_id="abc123", container_name="nginx")


def _run(monkeypatch, task, result):
    calls = []

    def update_task(updated):
        calls.append(updated)
        return result

    monkeypatch.setattr("services.scheduling.scheduler.update_task", update_task)
    TaskManagementService()._save_updated_tasks([task])
    return calls


def _messages(caplog, level):
    return [r.getMessage() for r in caplog.records if r.levelno == level]


def test_a_refused_write_is_not_called_saved(monkeypatch, task, caplog):
    with caplog.at_level(logging.DEBUG):
        assert _run(monkeypatch, task, result=False) == [task]

    assert not any("Changes saved" in m for m in _messages(caplog, logging.INFO)), (
        "the panel reported a save that update_task refused")
    assert any("abc123" in m for m in _messages(caplog, logging.ERROR)), (
        "a task stayed active in the file and nothing said so")


def test_a_saved_task_is_reported_as_saved(monkeypatch, task, caplog):
    """Counter-check: the everyday case still reports the save."""
    with caplog.at_level(logging.DEBUG):
        _run(monkeypatch, task, result=True)

    assert any("abc123" in m for m in _messages(caplog, logging.INFO))
    assert _messages(caplog, logging.ERROR) == []


def test_one_refused_write_does_not_stop_the_others(monkeypatch, caplog):
    """Counter-check: the loop keeps going, as it did before."""
    first = SimpleNamespace(task_id="one", container_name="a")
    second = SimpleNamespace(task_id="two", container_name="b")
    seen = []

    def update_task(updated):
        seen.append(updated.task_id)
        return updated.task_id != "one"

    monkeypatch.setattr("services.scheduling.scheduler.update_task", update_task)
    with caplog.at_level(logging.DEBUG):
        TaskManagementService()._save_updated_tasks([first, second])

    assert seen == ["one", "two"]

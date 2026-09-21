# -*- coding: utf-8 -*-
"""Writing the task list does not change who may read it, and leaves nothing behind.

THE FINDING (review E1, section 26 - a section NEITHER review pass ever
looked at): `_save_raw_tasks_to_file` is a fourth hand-rolled
temp-file-and-rename, written before `utils/atomic_io.py` existed and never
moved onto it. Z7 says "every write to configuration or state files is
atomic", and in the crash sense this one is. Three things it does not do,
all of which the shared helper does:

1. **It does not keep the target's permissions.** `tempfile.mkstemp` creates
   its file 0600 and owned by whoever is writing; the rename then makes THAT
   the permissions of `tasks.json`. DDC writes this file from two processes -
   the bot and the web panel - and every save silently re-stamps it.

2. **It leaks the temp file when the write fails with an OSError.** The
   cleanup sits under `except (json.JSONDecodeError, ValueError, TypeError,
   UnicodeEncodeError)`, so a full disk during `json.dump` or `fsync` misses
   it entirely - and the outer retry loop then tries three times, leaving
   three orphans in the config directory per save, on every save, for as long
   as the disk stays full.

3. **Its Windows branch is not atomic.** `shutil.move` onto an existing file
   is a copy, not a replace; `os.replace` is atomic on both platforms and is
   what the shared helper uses.

Why this was not found before: the Z7 test covers the donation counter, one
of the five places fixed on 2026-09-16, and scans for nothing. A guarantee
that says "every write" is only worth the places somebody checked - and
nobody had ever read this section.
"""

import json
import os
import stat

import pytest

import services.scheduling.runtime as scheduler_runtime
import services.scheduling.scheduler as scheduler_mod

TASKS = [{"id": "t-1", "container_name": "nginx", "action": "start",
          "cycle": "daily", "hour": 4, "minute": 0}]


@pytest.fixture
def tasks_file(monkeypatch, tmp_path):
    monkeypatch.setenv("DDC_SCHEDULER_CONFIG_DIR", str(tmp_path))
    scheduler_runtime.reset_scheduler_runtime()
    fresh = scheduler_runtime.get_scheduler_runtime()
    monkeypatch.setattr(scheduler_mod, "_runtime", fresh)
    monkeypatch.setattr(scheduler_mod, "TASKS_FILE_PATH", fresh.tasks_file_path)
    fresh.ensure_layout()
    path = fresh.tasks_file_path
    path.write_text("[]", encoding="utf-8")
    os.chmod(path, 0o664)
    yield path
    scheduler_runtime.reset_scheduler_runtime()


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_a_save_keeps_the_permissions_the_file_had(tasks_file):
    """The file is written by two processes; a save must not re-stamp it."""
    assert _mode(tasks_file) == 0o664, "premise"

    assert scheduler_mod._save_raw_tasks_to_file(TASKS) is True

    assert _mode(tasks_file) == 0o664, (
        f"the task file came back as {oct(_mode(tasks_file))} - the temp file's "
        f"own 0600, handed to tasks.json by the rename"
    )


def test_a_failed_write_leaves_no_temp_file(tasks_file, monkeypatch):
    """A full disk must not leave litter in the config directory."""
    def _no_space(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", _no_space)
    monkeypatch.setattr(scheduler_mod.time, "sleep", lambda seconds: None)

    scheduler_mod._save_raw_tasks_to_file(TASKS)

    leftovers = [p.name for p in tasks_file.parent.iterdir()
                 if p.name != tasks_file.name]
    assert leftovers == [], (
        f"{len(leftovers)} temp file(s) left behind: {leftovers} - and the "
        f"retry loop makes three of them per save"
    )


def test_a_failed_write_leaves_the_old_list_intact(tasks_file, monkeypatch):
    """Z7's own promise, pinned here because this writer was never checked."""
    tasks_file.write_text(json.dumps([{"id": "old"}]), encoding="utf-8")

    def _no_space(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", _no_space)
    monkeypatch.setattr(scheduler_mod.time, "sleep", lambda seconds: None)

    scheduler_mod._save_raw_tasks_to_file(TASKS)

    assert json.loads(tasks_file.read_text(encoding="utf-8")) == [{"id": "old"}]


def test_a_save_still_writes_the_tasks(tasks_file):
    """The counter-case: none of the above may be bought with a write that does not happen."""
    assert scheduler_mod._save_raw_tasks_to_file(TASKS) is True

    assert json.loads(tasks_file.read_text(encoding="utf-8")) == TASKS


def test_the_file_keeps_the_shape_it_had(tasks_file):
    """Indent 4 and real characters - other readers and the unchanged-check rely on it.

    Written out in full rather than sampled: the first version asked whether
    "\n    " occurred anywhere, and a probe that switched the writer to
    indent=2 walked straight past it, because two levels of two spaces look
    exactly like one level of four.
    """
    data = [{"id": "t-1", "container_name": "Kaffeeküche"}]
    scheduler_mod._save_raw_tasks_to_file(data)

    raw = tasks_file.read_text(encoding="utf-8")
    assert raw == json.dumps(data, indent=4, ensure_ascii=False), (
        f"the file no longer has the shape it had:\n{raw[:200]}"
    )

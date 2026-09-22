# -*- coding: utf-8 -*-
"""Bot and web process do not lose each other's scheduled tasks.

THE FINDING: every writer of tasks.json does load -> change -> save, and the
only thing between them is a threading.RLock. The bot and the web panel are
two PROCESSES (supervisord starts discord-bot and web-ui), so that lock
serialises nothing between them: if both read before either writes, the
second write replaces the file with a state that never saw the first one's
change. A task the operator just deleted in the panel comes back because the
bot wrote its list a second later - and the panel said the delete worked.
An atomic write gives an atomic swap, not an atomic read-modify-write.

The same file lock the query-support service already uses for exactly this
now spans the whole cycle.

COUNTER-CHECK (2026-09-22): red before - with the two processes interleaved
the file held one task instead of two.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

WRITER = textwrap.dedent('''
    import sys, time
    sys.path.insert(0, {root!r})
    from services.scheduling import scheduler

    # widen the window between this process's read and its write
    real_write = scheduler._save_raw_tasks_to_file
    def slow_write(data):
        time.sleep({delay})
        return real_write(data)
    scheduler._save_raw_tasks_to_file = slow_write

    task = scheduler.ScheduledTask(container_name={container!r}, action="restart",
                                   cycle="daily", schedule_details={{"time": {time!r}}},
                                   timezone_str="Europe/Berlin")
    task.calculate_next_run()
    print(scheduler.add_task(task))
''')


def _writer(tmp_path, container, delay, at):
    script = WRITER.format(root=str(ROOT), delay=delay, container=container, time=at)
    environment = dict(os.environ, DDC_CONFIG_DIR=str(tmp_path))
    return subprocess.Popen([sys.executable, "-c", script], env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_both_processes_keep_their_task(tmp_path):
    (tmp_path / "tasks.json").write_text("[]", encoding="utf-8")

    first = _writer(tmp_path, "alpha", delay=0.8, at="03:00")
    import time

    time.sleep(0.2)                       # the second process reads while the first holds
    second = _writer(tmp_path, "beta", delay=0.0, at="04:00")
    for process in (first, second):
        assert process.wait(timeout=60) == 0, process.stderr.read()

    stored = json.loads((tmp_path / "tasks.json").read_text(encoding="utf-8"))
    names = sorted(task["container"] for task in stored)  # the stored key is "container"
    assert names == ["alpha", "beta"], f"a task was lost: {names}"

# -*- coding: utf-8 -*-
"""
THE FINDING (review C36, section 36 F6, F7 and F8): `utils/performance_metrics.py`
is a self-contained measuring tool with three defects that all say the same
thing - it is not fit to be picked up.

F6: `self.metrics_dir = Path("data/metrics")` is relative to the process's
    current working directory, not to a fixed data root. The bot and the web
    part do not share a working directory, so they would measure into two
    different places - the exact pattern the SPEC records as a previously fixed
    bug for MechResetService and the config directory.

F7: `current_operations` is keyed by the OPERATION NAME and written without a
    lock. Two threads that start the same operation before either ends it
    overwrite each other's start time; whichever end() runs first pops the
    shared value, and both durations are measured from the wrong moment. The
    public shape stays as the archived document shows it - start(name) /
    end(name) - so the key carries the thread instead.

F8: `cleanup_old_metrics()` copies the file line by line into a temp file and
    then replaces the original. A line appended between the read reaching EOF
    and the replace is discarded the instant the replace happens - no error, no
    log line.

WHAT IS TRUE ABOUT THE REACH: nothing in the project calls this module. Its
only mentions outside itself are in `docs/archive/PERFORMANCE.md`, which
describes it as available and shows how to use it. So nothing is broken in
production today - this is a trap for whoever follows that document. It was
fixed rather than deleted for the same reason as review C30: the documentation
points at it, and a measuring tool that quietly measures wrong is worse than
none.

Three findings in one commit, deliberately: they are one statement about one
unused module, and one test file covers them. Everything else in this
programme is one finding per commit.

The counter-checks keep the tool a tool: a normal start/end pair still measures
the real duration, and cleanup still removes what it is supposed to remove.
"""

import json
import threading
import time
from pathlib import Path

import pytest

from utils import performance_metrics as pm


@pytest.fixture
def metrics(tmp_path, monkeypatch):
    """A fresh instance, measuring into a directory of its own."""
    monkeypatch.setattr(pm.PerformanceMetrics, "_instance", None, raising=False)
    monkeypatch.setenv("DDC_CONFIG_DIR", str(tmp_path))
    instance = pm.PerformanceMetrics.__new__(pm.PerformanceMetrics)
    instance.__init__()
    return instance


def test_the_metrics_directory_does_not_depend_on_the_working_directory(metrics):
    """F6: two processes with different working directories must not measure
    into two different places."""
    assert metrics.metrics_dir.is_absolute(), metrics.metrics_dir


def test_two_threads_measuring_the_same_operation_do_not_collide(metrics):
    """F7: the same operation name from two threads, and both durations have to
    be about their own work - not one measured from the other's start."""
    durations = []
    barrier = threading.Barrier(2)

    def _work(sleep_for):
        metrics.start("docker_operation")
        barrier.wait()
        time.sleep(sleep_for)
        durations.append(metrics.end("docker_operation"))

    threads = [threading.Thread(target=_work, args=(s,)) for s in (0.30, 0.05)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(durations) == 2
    long_one, short_one = max(durations), min(durations)
    # Each has to be about its OWN work. On the broken version the long one is
    # reported as 0.0, because the short one popped the shared start time and
    # left nothing behind.
    assert 0.25 <= long_one < 0.60, f"the long one was measured as {long_one:.3f}s"
    assert 0.03 <= short_one < 0.20, f"the short one was measured as {short_one:.3f}s"


def test_a_line_written_during_cleanup_is_not_lost(metrics, monkeypatch):
    """F8: the window is between the read reaching EOF and the replace().

    A writer that lands in it appends to a file that is about to be thrown
    away. The test opens that window deliberately - `replace()` lets a writer
    thread loose and waits - and asserts that the writer could NOT get in.
    """
    recent = time.time()
    metrics.metrics_file.write_text(
        json.dumps({"operation": "old", "end_time": recent}) + "\n", encoding="utf-8")

    entry = pm.MetricEntry(operation="fresh", start_time=recent, end_time=recent,
                           duration=0.0, success=True,
                           timestamp="2026-09-20T00:00:00", metadata={})
    writer = threading.Thread(target=metrics._write_metric, args=(entry,))
    real_replace = Path.replace

    def _replace_with_a_window(self, target):
        if ".tmp" in self.name:
            writer.start()
            time.sleep(0.1)          # the window: the read is done, the swap is not
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", _replace_with_a_window)
    metrics.cleanup_old_metrics(days=1)
    writer.join(timeout=5)

    kept = metrics.metrics_file.read_text(encoding="utf-8")
    assert "fresh" in kept, "the line written during the cleanup was discarded"


def test_a_single_measurement_is_still_measured(metrics):
    """COUNTER-CHECK: the tool still measures."""
    metrics.start("one_thing")
    time.sleep(0.05)
    duration = metrics.end("one_thing")

    assert 0.04 <= duration < 0.5


def test_cleanup_still_removes_what_is_old(metrics):
    """COUNTER-CHECK: keeping fresh lines is not keeping everything."""
    lines = [json.dumps({"operation": "ancient", "end_time": 0.0}),
             json.dumps({"operation": "recent", "end_time": time.time()})]
    metrics.metrics_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    removed = metrics.cleanup_old_metrics(days=1)

    kept = metrics.metrics_file.read_text(encoding="utf-8")
    assert removed == 1
    assert "ancient" not in kept and "recent" in kept

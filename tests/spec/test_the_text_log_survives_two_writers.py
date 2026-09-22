# -*- coding: utf-8 -*-
"""No action line is lost when two writers meet at a rotation.

THE FINDING (review D13, pass 2, section 18 F1): `_save_to_json` runs under
`_JSON_LOG_LOCK`, and the comment above that lock says exactly why - "actions
are logged from waitress threads and the bot event loop at the same time".
`_save_to_text`, called from the same `log_action`, ran with no lock at all:
neither the size check and the numbered renames in
`_rotate_text_log_if_needed`, nor the `open(..., 'a')` append after them.

Two writers can both pass the size check and then both rename the live file
onto `user_actions.log.1`, so the second rename overwrites what the first one
had just rotated away - a whole file of action history gone, with nothing in
the log about it.
"""

import threading

import pytest

from services.infrastructure import action_log_service as module
from services.infrastructure.action_log_service import ActionLogService

LINES_PER_WRITER = 40


@pytest.fixture
def service(tmp_path, monkeypatch):
    """A log that rotates often and keeps every backup, so nothing is
    discarded on purpose and a missing line is a lost line.

    The interleaving is FORCED, not hoped for: a barrier inside the rename
    holds the first writer there until the second one arrives. Without a lock
    both are then past the size check and both rename the live file onto
    `.1`, and the second overwrites what the first rotated away. With a lock
    the second writer cannot reach the barrier, the first times out after a
    moment and carries on - so the test is red for the defect and green for
    the fix, every run. The first version of this file relied on the race
    happening by itself; it went red once and then passed with the lock
    removed, which is no test at all.
    """
    monkeypatch.setattr(module, "_TEXT_LOG_MAX_BYTES", 400)
    monkeypatch.setattr(module, "_TEXT_LOG_BACKUP_COUNT", 200)

    from pathlib import Path
    real_rename = Path.rename
    barrier = threading.Barrier(2)
    log_name = (tmp_path / "user_actions.log").name

    def _rename_at_the_barrier(self, target):
        if self.name == log_name:          # only the live file's rotation
            try:
                barrier.wait(timeout=0.25)
            except threading.BrokenBarrierError:
                pass                       # alone here: the lock did its work
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", _rename_at_the_barrier)
    return ActionLogService(logs_dir=str(tmp_path))


def _write(service, tag):
    for number in range(LINES_PER_WRITER):
        service.log_action("START", f"container-{number}", user=tag, source=tag,
                           details="-")


def _all_lines(service):
    lines = []
    for path in service.logs_dir.iterdir():
        if path.name.startswith(service.text_log_file.name):
            lines.extend(l for l in path.read_text(encoding="utf-8").splitlines() if l)
    return lines


def test_no_line_is_lost_at_a_rotation(service):
    threads = [threading.Thread(target=_write, args=(service, tag))
               for tag in ("panel", "bot")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = _all_lines(service)
    assert len(lines) == 2 * LINES_PER_WRITER, (
        f"{2 * LINES_PER_WRITER} actions were logged and {len(lines)} survived"
    )


def test_every_line_is_whole(service):
    """Two appends must not end up inside one another."""
    threads = [threading.Thread(target=_write, args=(service, tag))
               for tag in ("panel", "bot")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    for line in _all_lines(service):
        assert line.count("|") == 4, f"garbled line: {line!r}"
        assert line.split("|")[2] in ("panel", "bot"), f"garbled line: {line!r}"


def test_one_writer_still_rotates(service):
    """Counter-check: the rotation itself must keep working."""
    _write(service, "solo")

    assert service._text_backup_path(1).exists()
    assert len(_all_lines(service)) == LINES_PER_WRITER

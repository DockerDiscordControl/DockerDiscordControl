# -*- coding: utf-8 -*-
"""The edit loop batches plainly - and its log says that, not something else.

THE FINDING: the periodic edit loop sorted this cycle's tasks into "slow" and
"fast" containers by reading a coroutine's frame through task._coro - an
attribute of asyncio.Task, which these are not: tasks_to_run holds bare
coroutines. Every task therefore fell into the fast list, the distribution
did nothing, and every cycle logged "0 slow containers distributed across N
batches" - a claim about work that never happened, with a hard-coded list of
four of the operator's game servers behind it.

The batching is what it always was: chunks of BATCH_SIZE, in order. It says
that now.

COUNTER-CHECK (2026-09-22): red before - the frame inspection and the
"distributed" line were still there; the helper's own cases fail if the
chunking is changed.
"""

from pathlib import Path

import pytest

from cogs.message_updates import in_batches

SOURCE = (Path(__file__).resolve().parents[2] / "cogs" / "message_updates.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("count,size,expected", [
    (0, 5, []),
    (3, 5, [3]),
    (10, 5, [5, 5]),
    (11, 5, [5, 5, 1]),
])
def test_tasks_are_chunked_in_order(count, size, expected):
    items = list(range(count))

    batches = in_batches(items, size)

    assert [len(batch) for batch in batches] == expected
    assert [item for batch in batches for item in batch] == items


def test_the_dead_frame_inspection_is_gone():
    # The words survive in the comment that explains why the code went; the CODE
    # that read a coroutine's frame does not.
    assert "cr_frame" not in SOURCE
    assert "KNOWN_SLOW_CONTAINERS" not in SOURCE


def test_the_log_does_not_claim_a_distribution():
    assert "slow containers distributed" not in SOURCE

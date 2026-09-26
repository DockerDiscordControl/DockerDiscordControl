# -*- coding: utf-8 -*-
"""A paused container, or one Docker is restarting, is not reported as stopped.

THE FINDING, measured live on the operator's server on 2026-09-26: after
`docker pause`, the watchdog reported "Container 'ddc-watchdog-probe' stopped
(it was running)". DDC derives "running" from container.status == 'running',
and Docker's status is "paused" for a paused container and "restarting" while
its own restart policy brings one back - State.Running is true in both. A
"restart on stopped" rule would restart a container somebody paused on
purpose, or race Docker's own restart manager.

OPERATOR DECISION (2026-09-26): paused counts as running - for the WATCHDOG.
The panel and the Discord overview keep showing what they show; this is about
whether a stop happened.

HOW THIS TEST CAN FAIL: the watchdog is handed "not running" for a paused or
restarting container, or "running" for an exited one.

COUNTER-CHECK (2026-09-26): red before the fix - the helper did not exist and
the status loop built ContainerState from result.is_running alone.
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.automation.container_watch import running_for_the_watchdog


@pytest.mark.parametrize("status", ["running", "paused", "restarting"])
def test_these_are_up(status):
    result = SimpleNamespace(is_running=(status == "running"), status=status)

    assert running_for_the_watchdog(result) is True


@pytest.mark.parametrize("status", ["exited", "created", "dead", "removing", None])
def test_these_are_down(status):
    result = SimpleNamespace(is_running=False, status=status)

    assert running_for_the_watchdog(result) is False


def test_the_status_loop_asks_it():
    """The call site: the snapshot the watchers see is built with it."""
    source = (Path(__file__).resolve().parents[2] / "cogs" / "background_loops.py").read_text(
        encoding="utf-8")

    assert re.search(r"ContainerState\(running_for_the_watchdog\(result\)", source), (
        "the watchdog's snapshot is not built from running_for_the_watchdog")

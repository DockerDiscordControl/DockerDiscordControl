# -*- coding: utf-8 -*-
"""The performance test survives the container it cannot measure.

THE FINDING (review C57, section 16, found while working on F4): both error
handlers in ``test_docker_performance`` build their result entry with
``'timeout_config': get_container_timeouts(container_name)`` - a call that
reads the configuration and can raise. It is also the call that can put the
loop into those handlers in the first place. So when the timeout lookup was
what failed, the handler ran it again, raised the same error a second time,
and the exception left ``test_docker_performance`` altogether: a diagnostic
tool dying on the one container it was asked to diagnose, taking the report
on all the other containers with it.

(The function is named ``test_docker_performance`` in production code. It is
reached here through the module, never imported by name, so pytest does not
collect it.)
"""

import pytest

from services.docker_service import docker_utils

TIMEOUTS = {"info_timeout": 5, "stats_timeout": 5, "container_type": "standard"}


@pytest.fixture
def quick_docker(monkeypatch):
    """Info and stats answer at once, so nothing else can fail."""
    async def _info(name):
        return {"name": name}

    async def _stats(name):
        return ("1.0%", "10MiB")

    monkeypatch.setattr(docker_utils, "get_docker_info", _info)
    monkeypatch.setattr(docker_utils, "get_docker_stats", _stats)


def _timeouts_that_fail_for(broken):
    def _get(container_name):
        if container_name == broken:
            raise RuntimeError("docker daemon is not reachable for this container")
        return dict(TIMEOUTS)
    return _get


@pytest.mark.asyncio
async def test_the_report_survives_a_container_it_cannot_measure(
        quick_docker, monkeypatch):
    monkeypatch.setattr(docker_utils, "get_container_timeouts",
                        _timeouts_that_fail_for("broken"))

    results = await docker_utils.test_docker_performance(["good", "broken"],
                                                         iterations=2)

    assert results["container_results"]["good"]["times_ms"], (
        "one container could not be measured and the whole report is gone"
    )


@pytest.mark.asyncio
async def test_the_container_that_failed_is_named(quick_docker, monkeypatch):
    monkeypatch.setattr(docker_utils, "get_container_timeouts",
                        _timeouts_that_fail_for("broken"))

    results = await docker_utils.test_docker_performance(["good", "broken"],
                                                         iterations=1)

    assert results["container_results"]["broken"]["errors"], (
        "the container failed on every iteration and the report says nothing about it"
    )
    # And no invented configuration: a made-up default here would tell the
    # operator this container runs on a 0 s timeout, which is a false diagnosis
    # in a diagnostic tool (found by mutation M3 of review C57).
    assert results["container_results"]["broken"]["timeout_config"] is None, (
        "the timeout configuration was never read, and the report shows one anyway"
    )


@pytest.mark.asyncio
async def test_a_sound_run_still_measures_everything(quick_docker, monkeypatch):
    """Counter-check: surviving an error must not mean measuring nothing."""
    monkeypatch.setattr(docker_utils, "get_container_timeouts",
                        lambda name: dict(TIMEOUTS))

    results = await docker_utils.test_docker_performance(["a", "b"], iterations=1)

    assert results["container_results"]["a"]["times_ms"]
    assert results["container_results"]["b"]["times_ms"]
    assert results["container_results"]["a"]["timeout_config"] == TIMEOUTS

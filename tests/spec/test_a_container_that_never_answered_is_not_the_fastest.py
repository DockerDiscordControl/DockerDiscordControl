# -*- coding: utf-8 -*-
"""A container that never answered is not the fastest one.

THE FINDING (review C58, section 16 F4): ``test_docker_performance`` records
a container that raised on every iteration in ``errors``, but never puts a
time into its ``times_ms``. Its ``average_ms`` therefore keeps the initial
value 0. The summary then took

    min(results['container_results'].items(), key=lambda x: x[1]['average_ms'])

over ALL containers, that one included - so the container that answered
nothing at all was presented to the operator as the fastest, at 0 ms. This
is a diagnostic tool; the one thing it must not do is point away from the
container that is broken.

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
async def test_a_container_that_only_ever_failed_is_not_the_fastest(
        quick_docker, monkeypatch):
    monkeypatch.setattr(docker_utils, "get_container_timeouts",
                        _timeouts_that_fail_for("broken"))

    results = await docker_utils.test_docker_performance(["good", "broken"],
                                                         iterations=2)

    assert results["summary"]["fastest_container"]["name"] == "good", (
        "the container that answered nothing at all is presented as the quickest one"
    )


@pytest.mark.asyncio
async def test_it_is_not_the_slowest_either(quick_docker, monkeypatch):
    """The same 0 ms would keep it out of the slowest slot just as wrongly."""
    monkeypatch.setattr(docker_utils, "get_container_timeouts",
                        _timeouts_that_fail_for("broken"))

    results = await docker_utils.test_docker_performance(["good", "broken"],
                                                         iterations=2)

    assert results["summary"]["slowest_container"]["name"] == "good"


@pytest.mark.asyncio
async def test_two_working_containers_are_still_ranked(quick_docker, monkeypatch):
    """Counter-check: the ranking itself must keep working."""
    monkeypatch.setattr(docker_utils, "get_container_timeouts",
                        lambda name: dict(TIMEOUTS))

    results = await docker_utils.test_docker_performance(["a", "b"], iterations=1)

    names = {results["summary"]["fastest_container"]["name"],
             results["summary"]["slowest_container"]["name"]}
    assert names <= {"a", "b"}
    assert results["summary"]["fastest_container"]["average_ms"] <= \
        results["summary"]["slowest_container"]["average_ms"]
    assert results["summary"]["fastest_container"]["average_ms"] > 0


@pytest.mark.asyncio
async def test_a_measured_container_with_an_error_stays_in_the_ranking(monkeypatch):
    """An error is not the same as no measurement.

    A container that answers slowly and reports a stats timeout is exactly the
    one the operator is looking for. Ranking only the error-free containers
    would drop it from the report (found by mutation M2 of review C58).
    """
    import asyncio

    async def _info(name):
        return {"name": name}

    async def _stats(name):
        if name == "slow":
            await asyncio.sleep(0.02)
            return ("N/A", "N/A")       # a stats timeout: recorded as an error
        return ("1.0%", "10MiB")

    monkeypatch.setattr(docker_utils, "get_docker_info", _info)
    monkeypatch.setattr(docker_utils, "get_docker_stats", _stats)
    monkeypatch.setattr(docker_utils, "get_container_timeouts",
                        lambda name: dict(TIMEOUTS))

    results = await docker_utils.test_docker_performance(["fast", "slow"], iterations=1)

    assert results["container_results"]["slow"]["errors"]
    assert results["summary"]["slowest_container"]["name"] == "slow", (
        "the container that took longest and reported an error is missing from the ranking"
    )

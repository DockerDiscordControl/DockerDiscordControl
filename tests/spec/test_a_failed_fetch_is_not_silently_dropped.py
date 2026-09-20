# -*- coding: utf-8 -*-
"""A container whose fetch failed still gets an answer.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 08 F5, re-checked 2026-09-20):
``bulk_fetch_container_status`` promises - in its docstring and in the
comment right above the loop, "ALWAYS WITH COMPLETE DATA" - a result for
every container it was asked about. When a fetch came back as an exception,
it logged, counted it and ``continue``d, so that container was simply absent
from the returned dict. The caller cannot tell "the fetch failed" from
"never asked": the entry is missing, the status cache keeps whatever it had,
and the overview shows a container that quietly stopped being updated.

The order is known - the fast containers in order, then the slow ones - so
the failed fetch can be named instead of dropped.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.status_handlers import StatusHandlersMixin

NAMES = ["alpha", "beta"]


def _servers():
    service = MagicMock()
    service.get_all_servers.return_value = [
        {"docker_name": name, "name": name.title(), "allow_detailed_status": True}
        for name in NAMES
    ]
    return service


def _connectivity():
    service = MagicMock()
    service.check_connectivity = AsyncMock(
        return_value=MagicMock(is_connected=True, error_message=None))
    return service


def _fetch_service(failing):
    """Answers for every container; raises for the one named in ``failing``."""
    service = MagicMock()

    async def fetch(container_name, *args, **kwargs):
        if container_name == failing:
            raise RuntimeError("docker did not answer")
        return (container_name, {"State": {"Status": "running", "Running": True}}, {})

    service.fetch_with_retries = fetch
    return service


async def _bulk(failing=None):
    mixin = StatusHandlersMixin()
    mixin.bot = None
    performance = MagicMock()
    performance.classify_containers.return_value = MagicMock(
        fast_containers=list(NAMES), slow_containers=[], unknown_containers=[])
    with patch("cogs.status_handlers.get_performance_service", return_value=performance), \
         patch("cogs.status_handlers.get_fetch_service",
               return_value=_fetch_service(failing)), \
         patch("cogs.status_handlers.get_server_config_service", return_value=_servers()), \
         patch("services.infrastructure.docker_connectivity_service."
               "get_docker_connectivity_service", return_value=_connectivity()):
        return await mixin.bulk_fetch_container_status(list(NAMES))


@pytest.mark.asyncio
async def test_every_container_is_answered_when_all_fetches_work():
    """Premise: without a failure both containers are in the answer."""
    results = await _bulk()

    assert sorted(results) == NAMES


@pytest.mark.asyncio
async def test_a_container_whose_fetch_raised_is_still_in_the_answer():
    results = await _bulk(failing="beta")

    assert sorted(results) == NAMES, (
        "the fetch for 'beta' raised and the container vanished from the answer"
    )
    assert results["beta"].success is False, "a failed fetch must not look like a success"
    assert results["alpha"].success is True, "the other container is unaffected"

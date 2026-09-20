# -*- coding: utf-8 -*-
"""One Docker answer, one verdict - in both status paths.

No ``@covers`` marker: a finding, not a guarantee.

THE FINDING (stage 4 review, stage B, section 08 F2, re-checked 2026-09-20):
the two paths that ask Docker about a container disagree about when it is
gone. ``bulk_fetch_container_status`` asks ``if info is None and
is_container_not_found(...)``, ``get_status`` asks ``if not info and
is_container_not_found(...)``. For an answer that is empty but not None - an
empty dict - the single path says "not found" while the bulk path calls it
offline. The same container then reads 🔴 in the overview and "not found" in
its own panel, depending on which loop last touched it, and the comment in
the single path says the two are meant to be the same state.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cogs.status_handlers import StatusHandlersMixin

NAME = "vrising"
SERVER = {"docker_name": NAME, "name": "V-Rising", "allow_detailed_status": True}


class _Cache:
    def __init__(self):
        self.entries = {}

    def get(self, name):
        return self.entries.get(name)

    def set(self, name, data, timestamp=None):
        self.entries[name] = data

    def set_error(self, name, error):
        self.entries[name] = error


def _mixin():
    mixin = StatusHandlersMixin()
    mixin.bot = MagicMock()
    mixin.status_cache_service = _Cache()
    return mixin


def _servers():
    service = MagicMock()
    service.get_all_servers.return_value = [SERVER]
    service.get_server_by_docker_name.return_value = SERVER
    return service


def _status_service(not_found):
    service = MagicMock()
    service.is_container_not_found.return_value = not_found
    return service


def _connectivity():
    service = MagicMock()
    service.check_connectivity = AsyncMock(
        return_value=MagicMock(is_connected=True, error_message=None))
    return service


def _fetch_service(info):
    service = MagicMock()

    async def fetch(container_name, *args, **kwargs):
        return (container_name, info, {})

    service.fetch_with_retries = fetch
    return service


async def _bulk(info, not_found=True):
    mixin = _mixin()
    performance = MagicMock()
    performance.classify_containers.return_value = MagicMock(
        fast_containers=[NAME], slow_containers=[], unknown_containers=[])
    with patch("cogs.status_handlers.get_performance_service", return_value=performance), \
         patch("cogs.status_handlers.get_fetch_service", return_value=_fetch_service(info)), \
         patch("cogs.status_handlers.get_server_config_service", return_value=_servers()), \
         patch("cogs.status_handlers.get_container_status_service",
               return_value=_status_service(not_found)), \
         patch("services.infrastructure.docker_connectivity_service."
               "get_docker_connectivity_service", return_value=_connectivity()):
        results = await mixin.bulk_fetch_container_status([NAME])
    return results[NAME]


async def _single(info, not_found=True):
    mixin = _mixin()
    with patch("cogs.status_handlers.get_docker_info_dict_service_first",
               new_callable=AsyncMock, return_value=info), \
         patch("cogs.status_handlers.get_docker_stats_service_first",
               new_callable=AsyncMock, return_value={}), \
         patch("cogs.status_handlers.get_container_status_service",
               return_value=_status_service(not_found)):
        return await mixin.get_status(SERVER)


def _is_not_found(result):
    return getattr(result, "not_found", None) is True or "not" in str(
        getattr(result, "status_text", "")).lower()


@pytest.mark.asyncio
async def test_both_paths_say_not_found_for_no_answer():
    """Premise: with no answer at all the two already agree."""
    assert _is_not_found(await _bulk(None)), "bulk path"
    assert _is_not_found(await _single(None)), "single path"


@pytest.mark.asyncio
async def test_both_paths_say_not_found_for_an_empty_answer():
    single = await _single({})
    bulk = await _bulk({})

    assert _is_not_found(single), "premise: the single path calls an empty answer not found"
    assert _is_not_found(bulk), (
        "the bulk path calls the same empty answer something else - one container, "
        "two verdicts"
    )


@pytest.mark.asyncio
async def test_a_container_docker_knows_is_not_not_found():
    """Counter-check: a real answer must not become "not found"."""
    running = {"State": {"Status": "running", "Running": True}}

    assert not _is_not_found(await _bulk(running, not_found=False))
    assert not _is_not_found(await _single(running, not_found=False))


@pytest.mark.asyncio
async def test_an_empty_answer_alone_is_not_enough():
    """Counter-check: Docker decides, not the emptiness of one reply.

    Added after a mutation that dropped the is_container_not_found() question
    and called every empty answer "not found" - and nothing went red.
    """
    assert not _is_not_found(await _bulk({}, not_found=False)), (
        "an empty reply while Docker still knows the container is offline, not gone"
    )
    assert not _is_not_found(await _single({}, not_found=False))


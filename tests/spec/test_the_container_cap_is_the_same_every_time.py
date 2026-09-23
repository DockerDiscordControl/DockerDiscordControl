# -*- coding: utf-8 -*-
"""If the panel has to leave containers out, it leaves out the same ones.

THE FINDING (independent review of the Docker layer, 2026-09-23): the refresh
keeps at most `min(BACKGROUND_REFRESH_LIMIT, MAX_CACHED_CONTAINERS)` = 50
containers, and the truncation happens BEFORE the sort:

    containers_limited = containers_to_process[:effective_limit]
    ...
    docker_cache['containers'] = sorted(new_containers, key=...name)

So the survivors are the first 50 of Docker's OWN listing order - roughly
newest first - and that order changes whenever a container is created, removed
or restarted. Between two refreshes a different 50 can survive.

Two consequences, and the second is the one that matters:

* an operator with more than 50 containers sees only 50, with nothing in the
  panel saying so (only a logger.warning);
* WHICH 50 is not stable. A container can be in the list, vanish after the next
  refresh, and come back after the one after that - without anything about it
  having changed.

The cap itself is a deliberate guard: every container in that loop costs a
Docker call. What is not deliberate is deciding membership by an order nobody
chose. Sorting first makes the cut reproducible - the same containers every
time, by name - and the log says which ones were left out instead of only how
many.

HOW THIS TEST CAN FAIL: it refreshes twice with the SAME containers in a
different order, as Docker really reports them after a restart, and compares
the two results. A different set is red.

COUNTER-CHECK (2026-09-23): red before - the two refreshes kept different
containers. The other tests keep the everyday case: below the cap nothing is
dropped and the order is still alphabetical.
"""

from unittest.mock import MagicMock

import pytest

from app.utils import web_helpers as wh


class _Container:
    def __init__(self, name):
        self.id = f"{name}0123456789ab"
        self.name = name
        self.status = "running"
        self.attrs = {"Config": {"Image": f"{name}:latest"}}


def _client_listing(containers):
    client = MagicMock()
    client.containers.list.return_value = containers
    return client


@pytest.fixture
def cache(monkeypatch):
    original = wh.docker_cache
    fresh = {
        'global_timestamp': None, 'containers': [], 'error': None,
        'container_timestamps': {}, 'container_hashes': {},
        'bg_refresh_running': False, 'priority_containers': set(),
        'last_cleanup': None, 'access_count': 0,
    }
    monkeypatch.setattr(wh, "docker_cache", fresh)
    yield fresh
    monkeypatch.setattr(wh, "docker_cache", original)


@pytest.fixture
def logger():
    return MagicMock()


def _refresh(monkeypatch, logger, names):
    monkeypatch.setattr("services.docker_service.client_factory.build_docker_client",
                        lambda **kw: _client_listing([_Container(n) for n in names]))
    wh.update_docker_cache(logger)


def _names(cache):
    return [c['name'] for c in cache['containers']]


def _too_many():
    """More containers than the cap, named so the alphabet is not the order."""
    limit = min(wh.BACKGROUND_REFRESH_LIMIT, wh.MAX_CACHED_CONTAINERS)
    return [f"container-{index:03d}" for index in range(limit + 10)]


def test_the_same_containers_survive_every_time(monkeypatch, cache, logger):
    """THE FINDING: membership followed Docker's order, which shifts."""
    names = _too_many()

    _refresh(monkeypatch, logger, names)
    first = _names(cache)

    # Docker lists newest first; one restart is enough to reverse the tail.
    _refresh(monkeypatch, logger, list(reversed(names)))
    second = _names(cache)

    assert first == second, (
        "two refreshes of the SAME containers kept different ones - a container "
        "can vanish from the panel and come back without anything changing")


def test_the_cut_is_by_name(monkeypatch, cache, logger):
    """Reproducible means predictable: the first N by name."""
    names = _too_many()
    limit = min(wh.BACKGROUND_REFRESH_LIMIT, wh.MAX_CACHED_CONTAINERS)

    _refresh(monkeypatch, logger, list(reversed(names)))

    assert _names(cache) == sorted(names)[:limit]


def test_the_log_says_which_ones_were_left_out(monkeypatch, cache, logger):
    """A number alone does not tell the operator what is missing."""
    names = _too_many()

    _refresh(monkeypatch, logger, names)

    said = " ".join(str(call) for call in logger.warning.call_args_list)
    assert said, "nothing was logged about the containers that were dropped"
    assert sorted(names)[-1] in said, (
        f"the log does not name a container that was left out: {said[:300]}")


def test_below_the_cap_nothing_is_dropped(monkeypatch, cache, logger):
    """Counter-check: the everyday installation."""
    _refresh(monkeypatch, logger, ["beta", "alpha", "gamma"])

    assert _names(cache) == ["alpha", "beta", "gamma"]
    assert logger.warning.call_args_list == []


def test_the_list_is_still_alphabetical(monkeypatch, cache, logger):
    """Counter-check: sorting earlier must not lose the sorting."""
    _refresh(monkeypatch, logger, ["zeta", "alpha", "Mike"])

    assert _names(cache) == ["alpha", "Mike", "zeta"]

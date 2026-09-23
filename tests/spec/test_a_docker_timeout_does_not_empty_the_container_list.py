# -*- coding: utf-8 -*-
"""A Docker query that timed out does not empty the panel's container list.

THE FINDING (independent review of the Docker layer, 2026-09-23):
update_docker_cache asks the daemon for the container list and catches a
timeout like this:

    try:
        containers_to_process = client.containers.list(all=True)
    except Exception as te:
        if "Read timed out" in str(te) or "UnixHTTPConnectionPool" in str(te):
            logger.error(...)
            containers_to_process = []        # <-- and then carries on
        else:
            raise te

Carrying on means the ordinary success path: the cache's container list is
replaced with the empty one, the global timestamp is set to NOW, and - the
part that makes it a lie rather than a gap - ``error`` is set to None.

    the refresh worker runs every 30 s
    the proxy socket is gone, or the daemon is slow
    -> containers = [], timestamp = now, error = None
    -> get_docker_containers_live computes a young cache age and hands the
       empty list out as fresh, error-free data, again after every refresh

The operator sees an empty panel with no error banner. What happened is that
DDC could not reach Docker at all, and the list it had was correct.

The handler two steps down does the right thing for a DockerException: it sets
the error and leaves the list alone. The timeout special-case is a hole in
exactly that guard - and it is the one path that can produce a legitimately
EMPTY list, which is why the existing
test_a_failed_refresh_keeps_the_old_cache.py does not reach it: that one
injects its failure inside the per-container loop.

HOW THIS TEST CAN FAIL: it fills the cache, then makes the LIST CALL time out,
and asks what the panel would be handed. An empty list, or a missing error, is
red.

COUNTER-CHECK (2026-09-23): red before - the list came back empty with
error=None. The last test keeps the other end: a host that really has no
containers must still be able to empty the cache.
"""

import time
from unittest.mock import MagicMock

import docker
import pytest
import requests

from app.utils import web_helpers as wh


class _Container:
    def __init__(self, name, status="running"):
        self.id = f"{name}0123456789ab"
        self.name = name
        self.status = status
        self.attrs = {"Config": {"Image": f"{name}:latest"}}


def _client_listing(containers):
    client = MagicMock()
    client.containers.list.return_value = containers
    return client


def _client_that_times_out(error):
    client = MagicMock()
    client.containers.list.side_effect = error
    return client


@pytest.fixture
def cache(monkeypatch):
    original = wh.docker_cache
    fresh = {
        'global_timestamp': None,
        'containers': [],
        'error': None,
        'container_timestamps': {},
        'container_hashes': {},
        'bg_refresh_running': False,
        'priority_containers': set(),
        'last_cleanup': None,
        'access_count': 0,
    }
    monkeypatch.setattr(wh, "docker_cache", fresh)
    yield fresh
    monkeypatch.setattr(wh, "docker_cache", original)


@pytest.fixture
def logger():
    return MagicMock()


def _refresh_with(monkeypatch, logger, client):
    monkeypatch.setattr("services.docker_service.client_factory.build_docker_client",
                        lambda **kw: client)
    wh.update_docker_cache(logger)


def _fill(monkeypatch, logger):
    _refresh_with(monkeypatch, logger,
                  _client_listing([_Container("alpha"), _Container("beta")]))


# The two shapes the handler recognises, and the exception types docker-py
# really raises for them.
TIMEOUTS = [
    pytest.param(requests.exceptions.ReadTimeout("HTTPConnectionPool: Read timed out."),
                 id="read-timed-out"),
    pytest.param(requests.exceptions.ConnectionError(
        "UnixHTTPConnectionPool(host='localhost', port=None): Max retries exceeded"),
        id="socket-unreachable"),
]


@pytest.mark.parametrize("error", TIMEOUTS)
def test_the_previous_list_survives(monkeypatch, cache, logger, error):
    """THE FINDING: the panel went empty and called it fresh."""
    _fill(monkeypatch, logger)
    assert [c['name'] for c in cache['containers']] == ["alpha", "beta"]

    _refresh_with(monkeypatch, logger, _client_that_times_out(error))

    assert [c['name'] for c in cache['containers']] == ["alpha", "beta"], (
        "a query DDC could not get an answer to emptied the container list")


@pytest.mark.parametrize("error", TIMEOUTS)
def test_the_operator_is_told(monkeypatch, cache, logger, error):
    """An empty panel with no banner is the worst of both."""
    _fill(monkeypatch, logger)

    _refresh_with(monkeypatch, logger, _client_that_times_out(error))
    containers, reported = wh.get_docker_containers_live(logger)

    assert reported, "the panel was handed data with no error to show"
    assert [c['name'] for c in containers] == ["alpha", "beta"]


def test_a_host_with_no_containers_can_still_empty_the_cache(monkeypatch, cache, logger):
    """Counter-check: keeping the old list on failure must not keep it on an
    honest empty answer - the operator may really have removed everything."""
    _fill(monkeypatch, logger)

    _refresh_with(monkeypatch, logger, _client_listing([]))

    assert cache['containers'] == []
    assert cache['error'] is None


def test_a_working_refresh_is_unchanged(monkeypatch, cache, logger):
    """Counter-check: the everyday path."""
    _fill(monkeypatch, logger)
    first_stamp = cache['global_timestamp']
    time.sleep(0.01)

    _refresh_with(monkeypatch, logger, _client_listing([_Container("delta")]))

    assert [c['name'] for c in cache['containers']] == ["delta"]
    assert cache['global_timestamp'] > first_stamp
    assert cache['error'] is None

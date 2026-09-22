# -*- coding: utf-8 -*-
"""
THE FINDING (review C7, section 34 F1): ``update_docker_cache`` empties the
cache BEFORE it refills it:

    docker_cache['containers'] = []
    for container in containers_limited:
        ... docker_cache['containers'].append(container_data)
    docker_cache['global_timestamp'] = current_time

``container.image.tags`` reads from the Docker daemon, and an image that was
removed under a running container - Unraid does exactly this when it recreates
one - raises ``docker.errors.NotFound``, a ``DockerException``. The loop then
stops halfway. The outer handler sets a loud "DOCKER CONNECTIVITY FAILURE"
error, but it restores nothing: ``containers`` keeps the half-built list and
``global_timestamp`` still names the LAST SUCCESSFUL refresh, because it is only
written after the loop. For the whole remaining cache duration,
``get_docker_containers_live`` computes a young cache age from that untouched
timestamp and serves the truncated list as fresh data. Every container the loop
had not reached yet has silently vanished from the web panel.

``container_hashes`` has the same problem in reverse: the aborted run writes the
hashes of the containers it did reach, so the hash table then describes data
that was thrown away. The next refresh finds "nothing changed" for them and
leaves their per-container timestamp alone.

The counter-check (test_a_successful_refresh_does_replace_the_list) holds the
other end: keeping the old cache on failure must not turn into keeping it on
success.

SINCE REVIEW E53 the trigger described above is gone: the image name is read
from ``attrs['Config']['Image']`` and ``container.image`` is never requested,
so a removed image can no longer stop the loop. The guard stays anyway, with a
synthetic failure inside the loop, because build-then-swap is what protects
the cache against the NEXT per-container lookup someone adds to that loop.
"""

import time
from unittest.mock import MagicMock

import docker
import pytest

from app.utils import web_helpers as wh


class _Image:
    def __init__(self, tags, image_id="sha256:abcdef123456"):
        self.tags = tags
        self.id = image_id


class _Container:
    def __init__(self, name, status="running", tag=None, broken=False):
        self.id = f"{name}0123456789ab"
        self.name = name
        self._status = status
        self._image = _Image([tag or f"{name}:latest"])
        self._broken = broken
        self.attrs = {"Config": {"Image": tag or f"{name}:latest"}}

    @property
    def status(self):
        if self._broken:
            # A DockerException in the middle of the loop. Until review E53
            # this came from container.image, which the loop no longer reads.
            raise docker.errors.NotFound("container vanished mid-refresh")
        return self._status

    @property
    def image(self):
        return self._image


def _client_with(containers):
    client = MagicMock()
    client.containers.list.return_value = containers
    return client


@pytest.fixture
def cache(monkeypatch):
    """A private copy of the module-global cache, restored afterwards."""
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


def _refresh(monkeypatch, logger, containers):
    monkeypatch.setattr("services.docker_service.client_factory.build_docker_client", lambda **kw: _client_with(containers))
    wh.update_docker_cache(logger)


def _good_three():
    return [_Container("alpha"), _Container("beta"), _Container("gamma")]


def _second_one_broken():
    return [_Container("alpha"), _Container("beta", broken=True), _Container("gamma")]


def test_a_failed_refresh_keeps_the_previous_list(monkeypatch, cache, logger):
    """THE FINDING: a refresh that dies halfway must not leave half a cache."""
    _refresh(monkeypatch, logger, _good_three())
    assert [c['name'] for c in cache['containers']] == ["alpha", "beta", "gamma"]

    _refresh(monkeypatch, logger, _second_one_broken())

    assert [c['name'] for c in cache['containers']] == ["alpha", "beta", "gamma"]


def test_the_half_built_list_is_not_served_as_fresh(monkeypatch, cache, logger):
    """The old timestamp survives the failure, so whatever is in 'containers'
    is handed out as fresh cached data for the rest of the cache duration."""
    _refresh(monkeypatch, logger, _good_three())
    _refresh(monkeypatch, logger, _second_one_broken())

    containers, error = wh.get_docker_containers_live(logger)

    assert [c['name'] for c in containers] == ["alpha", "beta", "gamma"]
    assert error is not None, "the failure itself must still be reported"


def test_the_hashes_still_describe_the_cached_list(monkeypatch, cache, logger):
    """The hash table is the change detector for the NEXT refresh. After a
    failed refresh it must not describe data that was discarded."""
    _refresh(monkeypatch, logger, _good_three())
    hashes_before = dict(cache['container_hashes'])

    monkeypatch.setattr("services.docker_service.client_factory.build_docker_client", lambda **kw: _client_with(
        [_Container("alpha", status="exited"), _Container("beta", broken=True)]))
    wh.update_docker_cache(logger)

    assert cache['container_hashes'] == hashes_before


def test_a_successful_refresh_does_replace_the_list(monkeypatch, cache, logger):
    """COUNTER-CHECK: keeping the old cache on failure must not become keeping
    it on success - a working refresh replaces list and timestamp."""
    _refresh(monkeypatch, logger, _good_three())
    first_stamp = cache['global_timestamp']
    time.sleep(0.01)

    _refresh(monkeypatch, logger, [_Container("delta")])

    assert [c['name'] for c in cache['containers']] == ["delta"]
    assert cache['global_timestamp'] > first_stamp
    assert cache['error'] is None

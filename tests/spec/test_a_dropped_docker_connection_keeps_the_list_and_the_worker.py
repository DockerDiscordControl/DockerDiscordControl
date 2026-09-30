# -*- coding: utf-8 -*-
"""A dropped Docker connection keeps the cached list, the banner and the worker.

THE FINDING (stage 4 review before v3.1.0, section 34 pass 4):
update_docker_cache turned a failed list call into a DockerException only
by message text ("Read timed out", "UnixHTTPConnectionPool"). A requests
ConnectionError "('Connection aborted.', RemoteDisconnected(...))" or a
ChunkedEncodingError - the proxy or the daemon closing the connection
before or in the middle of an answer - was re-raised raw. No handler of
the cache update or of the refresh worker lists it, so the worker thread
ended with only the calm "worker stopped" line, and a page asking for the
list got a 500 instead of the "DOCKER CONNECTIVITY LOST" banner.

THE CONTRACT: any transport failure of the list call keeps the cached list
and sets the connectivity error; the worker survives what it did not
expect, and says so if it ever dies.

HOW THIS TEST CAN FAIL: the ConnectionError escapes again, or one
unexpected exception ends the worker.

COUNTER-CHECK (2026-09-30): red before the change (the ConnectionError
propagated from both).
"""

import http.client
import logging
from types import SimpleNamespace

import pytest
import requests
import urllib3

import app.utils.web_helpers as wh

LOGGER = logging.getLogger("spec.dropped_docker_connection")


def _aborted():
    return requests.exceptions.ConnectionError(urllib3.exceptions.ProtocolError(
        "Connection aborted.", http.client.RemoteDisconnected("Remote end closed connection without response")))


@pytest.mark.parametrize("failure", [_aborted, lambda: requests.exceptions.ChunkedEncodingError(
    "Connection broken: IncompleteRead(0 bytes read)")], ids=["aborted", "incomplete"])
def test_the_cached_list_stays_and_the_banner_is_set(monkeypatch, failure):
    cached = [{"name": "a", "status": "running"}]
    monkeypatch.setitem(wh.docker_cache, "containers", list(cached))
    monkeypatch.setitem(wh.docker_cache, "global_timestamp", 1.0)
    monkeypatch.setitem(wh.docker_cache, "error", None)

    def containers(all=True):
        raise failure()
    client = SimpleNamespace(api=SimpleNamespace(containers=containers))
    monkeypatch.setattr("services.docker_service.client_factory.build_docker_client",
                        lambda **kwargs: client)

    wh.update_docker_cache(LOGGER)

    assert wh.docker_cache["containers"] == cached
    assert str(wh.docker_cache["error"]).startswith("🚨 DOCKER CONNECTIVITY LOST")


def test_the_worker_survives_an_unexpected_error(monkeypatch):
    calls = []

    def update(logger):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("something nobody listed")
        wh.stop_background_thread.set()
    monkeypatch.setattr(wh, "update_docker_cache", update)
    monkeypatch.setattr(wh, "panel_is_active", lambda now=None: True)
    monkeypatch.setattr(wh, "HAS_GEVENT", False)
    monkeypatch.setattr(wh.time, "sleep", lambda seconds: None)
    wh.stop_background_thread.clear()
    try:
        wh.background_refresh_worker(LOGGER)
    finally:
        wh.stop_background_thread.clear()
    assert len(calls) == 2, "the worker ended after the first error"

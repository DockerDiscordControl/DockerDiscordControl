# -*- coding: utf-8 -*-
"""The web panel's container list is refreshed while the panel is used - and only then.

OPERATOR, 2026-09-28: the web panel is rarely open compared to Discord; refresh
on demand, and in the interval while it is open.

The panel's pages load the container list when they are called up and do not
poll it, so "open" means: a page was requested within PANEL_ACTIVE_SECONDS.
Docker's own healthcheck (/health, every few seconds) and static files do not
count - they would keep the panel "open" for good.

* While the panel is used, the worker refreshes in its interval as before.
* Idle, it asks Docker nothing.
* The first page after a pause gets a fresh list. Until then a list between
  DEFAULT_CACHE_DURATION and MAX_CACHE_AGE old (120-300 s here) was handed out
  as it was - harmless while the worker ran every 30 s, a five-minute-old
  panel once it pauses.

COUNTER-CHECK (2026-09-28): with the worker ignoring panel_is_active, the idle
case went red; with the old freshness window back, the after-a-pause case did;
with /health counted as a visit, the healthcheck case did.
"""

import logging
import time

import pytest
from flask import Flask

from app.utils import web_helpers as wh


@pytest.fixture
def cache(monkeypatch):
    fresh = {'global_timestamp': None, 'containers': [{'name': 'old'}], 'error': None,
             'container_timestamps': {}, 'container_hashes': {}, 'bg_refresh_running': False,
             'priority_containers': set(), 'last_cleanup': None, 'access_count': 0}
    monkeypatch.setattr(wh, "docker_cache", fresh)
    monkeypatch.setattr(wh, "ENABLE_BACKGROUND_REFRESH", False)
    monkeypatch.setattr(wh, "DEFAULT_CACHE_DURATION", 120)
    monkeypatch.setattr(wh, "BACKGROUND_REFRESH_INTERVAL", 30)
    return fresh


def _run_worker_once(monkeypatch, panel_last_used):
    refreshed = []
    monkeypatch.setattr(wh, "last_panel_request", panel_last_used)
    monkeypatch.setattr(wh, "update_docker_cache", lambda logger: refreshed.append(1))
    monkeypatch.setattr(wh, "HAS_GEVENT", False)
    # The first wait ends the worker: one cycle, then stop
    monkeypatch.setattr(wh.time, "sleep", lambda seconds: wh.stop_background_thread.set())
    wh.stop_background_thread.clear()
    try:
        wh.background_refresh_worker(logging.getLogger("test"))
    finally:
        wh.stop_background_thread.clear()
    return refreshed


def test_an_idle_panel_asks_docker_nothing(monkeypatch):
    assert _run_worker_once(monkeypatch, panel_last_used=time.time() - wh.PANEL_ACTIVE_SECONDS - 1) == []


def test_a_used_panel_is_refreshed_in_the_interval(monkeypatch):
    assert _run_worker_once(monkeypatch, panel_last_used=time.time() - 10) == [1]


def test_the_first_page_after_a_pause_gets_a_fresh_list(monkeypatch, cache):
    cache['global_timestamp'] = time.time() - 200  # older than 2 x 30 s, younger than MAX_CACHE_AGE

    def _refresh(logger):
        cache['containers'] = [{'name': 'fresh'}]
        cache['global_timestamp'] = time.time()
    monkeypatch.setattr(wh, "update_docker_cache", _refresh)
    containers, _ = wh.get_docker_containers_live(logging.getLogger("test"))
    assert [c['name'] for c in containers] == ['fresh'], "a 200-second-old list was handed out"


def test_a_young_list_is_served_from_the_cache(monkeypatch, cache):
    cache['global_timestamp'] = time.time() - 10
    monkeypatch.setattr(wh, "update_docker_cache",
                        lambda logger: pytest.fail("a young list was fetched again"))
    containers, _ = wh.get_docker_containers_live(logging.getLogger("test"))
    assert [c['name'] for c in containers] == ['old']


def test_the_healthcheck_does_not_keep_the_panel_open(monkeypatch):
    app = Flask(__name__)
    wh.register_panel_activity(app)
    app.add_url_rule("/health", "health", lambda: "ok")
    app.add_url_rule("/", "index", lambda: "panel")
    monkeypatch.setattr(wh, "last_panel_request", 0.0)
    client = app.test_client()
    client.get("/health")
    client.get("/static/panel.css")
    assert not wh.panel_is_active(), "Docker's healthcheck kept the panel 'open'"
    client.get("/")
    assert wh.panel_is_active()

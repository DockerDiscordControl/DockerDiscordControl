# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #
"""Audit 2026-09, package D1-1: background threads must survive web requests.

The cleanup used to be a ``teardown_appcontext`` hook, which Flask runs after every
request - it stopped the mech decay worker for good and the Docker cache refresh thread
until the next page load restarted it. It now runs only at process shutdown (atexit).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

import app.utils.web_helpers as web_helpers
import app.web.background as background


@pytest.fixture
def patched_background(monkeypatch):
    """Replace the real thread start/stop helpers and capture atexit registrations."""
    mocks = {
        name: MagicMock(name=name)
        for name in (
            "start_background_refresh",
            "start_mech_decay_background",
            "stop_background_refresh",
            "stop_mech_decay_background",
        )
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(background, name, mock)
    monkeypatch.setattr(background, "HAS_GEVENT", False)
    monkeypatch.setattr(background, "apply_gevent_fork_workaround", lambda logger: None)
    monkeypatch.setattr(background, "load_active_containers_from_config", lambda: [])
    monkeypatch.setattr(background, "_shutdown_hook_registered", False)
    monkeypatch.setenv("DDC_ENABLE_BACKGROUND_REFRESH", "true")
    monkeypatch.setenv("DDC_ENABLE_MECH_DECAY", "true")

    registered = []
    monkeypatch.setattr(background.atexit, "register", lambda fn, *args: registered.append((fn, args)))

    # Pretend both threads are running, so a cleanup would actually call the stop helpers.
    monkeypatch.setattr(web_helpers, "background_refresh_thread", object())
    monkeypatch.setattr(web_helpers, "mech_decay_thread", object())
    return mocks, registered


def _make_app() -> Flask:
    app = Flask(__name__)

    @app.route("/ping")
    def ping():
        return "ok"

    return app


def test_requests_do_not_stop_background_threads(patched_background):
    mocks, _ = patched_background
    app = _make_app()

    background.register_background_services(app)
    mocks["start_background_refresh"].assert_called_once()
    mocks["start_mech_decay_background"].assert_called_once()

    client = app.test_client()
    for _ in range(3):
        assert client.get("/ping").status_code == 200
    with app.app_context():
        pass

    mocks["stop_background_refresh"].assert_not_called()
    mocks["stop_mech_decay_background"].assert_not_called()
    assert app.teardown_appcontext_funcs == []


def test_shutdown_hook_stops_both_threads(patched_background):
    mocks, registered = patched_background
    background.register_background_services(_make_app())

    assert len(registered) == 1
    hook, args = registered[0]
    hook(*args)

    mocks["stop_background_refresh"].assert_called_once()
    mocks["stop_mech_decay_background"].assert_called_once()


def test_shutdown_hook_registered_only_once(patched_background):
    _, registered = patched_background
    background.register_background_services(_make_app())
    background.register_background_services(_make_app())

    assert len(registered) == 1

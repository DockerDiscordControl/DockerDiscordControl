# -*- coding: utf-8 -*-
"""A re-test whose worker never started is not a re-test that is running.

THE FINDING (review D24, pass 2, section 32 F2): ``/api/game-query/retest``
sets the container's ``testing`` flag and only then starts the thread that
does the work::

    support.set_testing(container_name, True)
    ...
    threading.Thread(target=_run_game_query_retest, ...).start()

The flag is cleared in exactly one place: the worker's own ``finally`` block.
If ``.start()`` falls over - "can't start new thread" when the process is out
of threads is the realistic case - that ``finally`` never runs, and nothing
else ever clears the flag. The route's own ``except`` lists
``(ValueError, TypeError, KeyError)``, none of which a failing thread start
raises, so it does not clean up either.

What the operator sees: the spinner next to the container says "testing"
while nothing is being tested, and it keeps saying so. The flag is stored in
the verdicts file, so it survives a restart of the panel and is read again
when the configuration page is rendered
(``configuration_page_service.py:517``). Only another re-test that manages to
start a worker ever takes it back.

This is the second way into the same stuck spinner. Pass 1 found the first one
(A10, the cleanup write being swallowed at DEBUG); this one sits two lines
higher up, before the worker exists at all.

The counter-case below matters as much as the finding: a re-test that DID
start must leave the flag standing, or the spinner would go out immediately
and the poll would report "not supported" before the first probe has run.
"""

import threading
from types import SimpleNamespace

import pytest
from flask import Flask

from app.blueprints.main_routes import main_bp


class _RefusingThread:
    """A thread that cannot be started - the resource-exhaustion case."""

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        raise RuntimeError("can't start new thread")


class _AcceptingThread:
    """A thread that starts and then does nothing - the worker stays out."""

    started = False

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        _AcceptingThread.started = True


@pytest.fixture
def client(monkeypatch):
    """The route with auth stubbed, plus the recorded state of the flag."""
    import app.auth as auth_module
    from services.infrastructure import game_query_support_service as support

    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda username, password: "admin")
    monkeypatch.setattr(auth_module.auth, "auth_error_callback",
                        lambda status: ("denied", status))

    flag = {}

    def _set_testing(name, testing=True, path=None):
        flag[name] = bool(testing)

    monkeypatch.setattr(support, "set_testing", _set_testing)
    # The host/port lookup is not what is under test here - answer it plainly
    # rather than letting it fail into the route's own inner handler.
    monkeypatch.setattr(
        "services.config.server_config_service.get_server_config_service",
        lambda: SimpleNamespace(get_server_by_docker_name=lambda name: {}),
    )

    app = Flask(__name__)
    app.config["TESTING"] = True
    # Without this the test client re-raises instead of answering, and what is
    # being checked is the state the request LEAVES BEHIND, not how it ends.
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.register_blueprint(main_bp)
    return app.test_client(), flag


def test_a_worker_that_never_started_leaves_no_spinner(client, monkeypatch):
    """The thread refuses to start: the flag must not survive the request."""
    http, flag = client
    monkeypatch.setattr(threading, "Thread", _RefusingThread)

    http.post("/api/game-query/retest", json={"container": "valheim"})

    assert flag.get("valheim") is not True, (
        "the re-test never started, and 'valheim' is still marked as being "
        "tested - the panel will show that spinner until some later re-test "
        "happens to clear it"
    )


def test_the_caller_is_not_told_it_is_running(client, monkeypatch):
    """Whatever the answer is, it must not claim the test is under way."""
    http, _ = client
    monkeypatch.setattr(threading, "Thread", _RefusingThread)

    response = http.post("/api/game-query/retest", json={"container": "valheim"})

    assert response.status_code != 200 or not (response.get_json() or {}).get("success"), (
        "the thread could not be started and the panel was told the test is "
        "running, so it starts polling for a verdict that nobody is producing"
    )


def test_a_started_re_test_keeps_its_spinner(client, monkeypatch):
    """The other direction - without this, "always clear it" would pass.

    The worker clears the flag itself when it is done. If the route cleared it
    too, the spinner would go out before the first probe and the poll would
    read the previous verdict as this test's result.
    """
    http, flag = client
    _AcceptingThread.started = False
    monkeypatch.setattr(threading, "Thread", _AcceptingThread)

    response = http.post("/api/game-query/retest", json={"container": "valheim"})

    assert _AcceptingThread.started, "the worker was not started at all"
    assert flag.get("valheim") is True, (
        "the re-test is running and the container is not marked as being "
        "tested, so the poll reads the OLD verdict as this test's answer"
    )
    assert response.get_json() == {"success": True, "status": "testing"}

# -*- coding: utf-8 -*-
"""The rate limit on the action log is the one that actually runs.

REFUTED AS STATED, pinned as a promise (review D30, pass 2, section 31 F3).

The finding says: "On every import of this module,
`from app.blueprints.log_routes import rate_limit` raises ImportError". The
import does fail - `log_routes.py` defines no `rate_limit` - but it is
wrapped in `try/except ImportError` with a fallback written for exactly that
case. Nothing crashes, and nothing ever did.

What IS true is smaller and worth writing down: the `try` branch is dead. The
comment beneath it reads "Fallback: Own rate limit implementation if import
fails", which presents as the exception what is in fact the rule. Every
request that has ever been rate-limited here was limited by the fallback.

Worse, an `except ImportError` around a module that does exist would also
swallow an ImportError raised INSIDE log_routes.py - a broken dependency
there would quietly turn into "use the fallback" with nobody told. That is
the shape this programme keeps finding (D5, D16, D19), and here it costs
nothing to remove, because the branch it guards can never be taken.

While checking, two facts about these two routes, recorded rather than acted
on:

  /action-log            rate-limited, and NOTHING in the panel calls it.
                         The log is read through log_bp.get_action_logs.
  /download-action-log   the button people actually press, NOT rate-limited.

So the limit guards a route with no caller. This is not a hole - both routes
sit behind @auth.login_required, and a rate limit is about load, not access -
and adding one to the download route would be inventing a requirement the
operator never asked for. It is written here so the next person does not have
to work it out again.

These tests are green before the repair and after it. They exist so that
deleting the dead branch cannot quietly take the working limit with it.
"""

import time

import pytest
from flask import Flask

import app.blueprints.action_log_routes as action_log_routes


@pytest.fixture
def client(monkeypatch, tmp_path):
    import app.auth as auth_module

    monkeypatch.setattr(auth_module.auth, "verify_password_callback",
                        lambda username, password: "admin")
    monkeypatch.setattr(auth_module.auth, "auth_error_callback",
                        lambda status: ("denied", status))

    log_file = tmp_path / "user_actions.json"
    log_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(action_log_routes, "ACTION_LOG_FILE", str(log_file))

    # The limiter's memory is module state and outlives a single request.
    monkeypatch.setattr(action_log_routes, "_last_log_request", {})

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(action_log_routes.action_log_bp)
    return app.test_client()


def _get(http, ip="10.0.0.1"):
    return http.get("/action-log", environ_base={"REMOTE_ADDR": ip})


def test_a_second_request_inside_the_window_is_refused(client):
    assert _get(client).status_code == 200
    second = _get(client)

    assert second.status_code == 429, (
        f"the action log was served twice in a row and the limit is "
        f"{action_log_routes._min_request_interval}s - status {second.status_code}"
    )


def test_another_address_is_not_held_back(client):
    """The counter-case: a limit that refuses everybody is not a limit."""
    assert _get(client, "10.0.0.1").status_code == 200

    assert _get(client, "10.0.0.2").status_code == 200, (
        "one caller's request held back a different address"
    )


def test_the_window_lets_go_again(client, monkeypatch):
    assert _get(client).status_code == 200

    later = time.time() + action_log_routes._min_request_interval + 1
    monkeypatch.setattr(action_log_routes.time, "time", lambda: later)

    assert _get(client).status_code == 200, (
        "the window passed and the caller is still being refused"
    )


def test_log_routes_still_has_no_rate_limit_of_its_own():
    """The fact the deletion rests on.

    If a `rate_limit` is ever added to log_routes.py, this goes red - and
    whoever adds it gets to decide, deliberately, which of the two guards the
    action log, instead of an import silently changing the answer.
    """
    import app.blueprints.log_routes as log_routes

    assert not hasattr(log_routes, "rate_limit"), (
        "log_routes now defines rate_limit; action_log_routes has its own and "
        "no longer looks for one there"
    )

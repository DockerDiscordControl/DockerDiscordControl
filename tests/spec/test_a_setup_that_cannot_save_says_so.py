# -*- coding: utf-8 -*-
"""A first-time setup that could not be written does not end in a blank page.

THE FINDING (review D25, pass 2, section 32 F3): ``POST /setup`` writes the
new password hash with ``update_config_fields``. That function reaches
``ConfigService.save_config``, which turns a failed write into::

    except (IOError, OSError, PermissionError) as e:
        raise ConfigSaveError(...)

``ConfigSaveError`` descends from ``ConfigServiceError`` -> ``DDCBaseException``
-> ``Exception``. It is NOT an ``OSError``. The route's three handlers cover
``(ImportError, AttributeError)``, ``(ValueError, TypeError)`` and
``(IOError, OSError)`` - so the one exception this write actually raises is
the one nobody catches.

``save_config_api``, 900 lines further up in the same file, catches it by name
with the comment "Config persistence errors (disk full, permission denied)
that escaped the save service". The two routes disagree about what a failed
config write looks like, and only one of them is right.

What the operator sees: this is FIRST-TIME setup - a fresh install, the config
directory mounted read-only or the disk full. ``setup.html`` sends the form
with ``fetch`` and calls ``r.json()`` on the answer. An unhandled exception
gives it a 500 HTML error page, ``r.json()`` throws, and the page shows
nothing at all. The one message that would name the cause - "Unable to save
configuration" - is already written in the route and is simply never reached.

The last test is the counter-case: without it, "catch everything and report
failure" would pass while a setup that worked reported an error too.
"""

import pytest
from flask import Flask

from services.exceptions import ConfigSaveError
from app.blueprints.main_routes import main_bp

PASSWORD = "Sehr-Gut-1234"


@pytest.fixture
def client(monkeypatch):
    """The setup route on a fresh install, with the config write to order."""
    monkeypatch.setattr("app.blueprints.main_routes.load_config",
                        lambda: {"web_ui_password_hash": None})
    monkeypatch.setattr("app.blueprints.main_routes.log_user_action",
                        lambda *a, **k: None)

    def _write(behaviour):
        def _update(fields):
            if isinstance(behaviour, BaseException):
                raise behaviour
            return behaviour
        monkeypatch.setattr("app.blueprints.main_routes.update_config_fields", _update)

    app = Flask(__name__)
    app.config["TESTING"] = True
    # The point is the ANSWER the setup page receives, not whether the
    # exception reaches the test - so let Flask answer as it would in production.
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.register_blueprint(main_bp)
    return app.test_client(), _write


def _setup(http):
    return http.post("/setup", data={"password": PASSWORD,
                                     "confirm_password": PASSWORD})


def test_a_config_that_cannot_be_written_is_not_a_finished_setup(client):
    """The write raises what it really raises: the page must be told."""
    http, write = client
    write(ConfigSaveError("config.json: read-only file system"))

    payload = _setup(http).get_json()

    assert payload is not None, (
        "the setup page asked to save and got no JSON back at all - it calls "
        "r.json() on this and shows nothing"
    )
    assert payload.get("success") is False, payload
    assert payload.get("error"), "the page is told it failed and not that it failed"


def test_the_answer_is_readable_by_the_page(client):
    """setup.html parses the answer as JSON - an HTML error page is not one."""
    http, write = client
    write(ConfigSaveError("config.json: read-only file system"))

    response = _setup(http)

    assert response.mimetype == "application/json", (
        f"the setup page receives {response.mimetype} and parses it as JSON"
    )


def test_a_write_that_fails_the_old_way_is_still_caught(client):
    """The handler that was already there keeps working - this is a pin."""
    http, write = client
    write(OSError("no space left on device"))

    payload = _setup(http).get_json()

    assert payload.get("success") is False, payload


def test_a_setup_that_saves_still_succeeds(client):
    """The counter-case: a working write must not report an error.

    Without this, catching everything and answering "failed" would satisfy the
    three tests above while breaking every real installation.
    """
    http, write = client
    write(True)

    payload = _setup(http).get_json()

    assert payload.get("success") is True, payload

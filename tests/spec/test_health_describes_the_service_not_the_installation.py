# -*- coding: utf-8 -*-
"""The unauthenticated /health endpoint says the service is up, and no more.

THE FINDING (2026-09-24), the same shape as review D8. There are 13 routes
without a login guard, and I read what each of them actually answers on the
operator's running panel. /health returned, to any caller:

    {"version": "v2.4.1", "servers_configured": 7,
     "docker": {"path": "proxy", "state": "ok"},
     "config_loaded": true, "first_time_setup_needed": false, ...}

The exact version tells whoever asks which published issues apply to this
installation, and the container count describes the machine. Neither says
whether the service is healthy, which is what the endpoint is for - and
nothing in DDC reads either field: the container's HEALTHCHECK opens the URL
and checks that it does not raise, and grep across the panel, the scripts and
the bot finds no reader. Only tests asserted them.

`docker` STAYS PUBLIC, and that is a decision, not an oversight. Whether DDC
can reach Docker at all is what "healthy" means for this service, and v3.0
step 11 (V3 §7) put that field there so a healthcheck can tell a dead proxy
from a dead daemon - the operator's first question at 3am, which must not need
a password. test_health_tells_the_proxy_from_docker.py reads it unauthenticated
and stays green.

D8 was the same sentence about a different field: `cache_directory` was handed
to any caller on the open internet, nothing read it, and the route stayed
public with the field gone. The route stays public here too.

WHAT STAYS UNAUTHENTICATED: status, service, timestamp - and, only while the
panel has no password at all, that first-time setup is needed and where. That
is not a disclosure: in exactly that state the setup page is open to anybody
who loads the panel, which is the design of a first run.

WHAT MOVES BEHIND THE LOGIN: everything that describes the installation. An
operator diagnosing by hand adds -u and gets the whole body back.

HOW THIS TEST CAN FAIL: putting an installation detail back in the public
body, losing the detail for an authenticated caller, or breaking the shape the
container probe needs.

COUNTER-CHECK (2026-09-24): red before - the public body carried the version
and the container count. Counter-checked again with two sabotage variants on a
green baseline: answering every caller in full, and answering nobody in full.
"""

import json
from types import SimpleNamespace

import pytest
from flask import Flask

from app.web import routes as web_routes

PUBLIC = ("status", "service", "timestamp", "docker")
PRIVATE = ("version", "servers_configured", "config_loaded")
AUTH = {"Authorization": "Basic YWRtaW46YWRtaW4="}   # admin:admin


@pytest.fixture
def app(monkeypatch):
    """The health route on a bare app, with a configured panel behind it."""
    monkeypatch.setenv("DDC_VERSION", "9.9.9")
    monkeypatch.setattr(web_routes, "load_config",
                        lambda: {"web_ui_password_hash": "set"})
    monkeypatch.setattr(web_routes, "get_server_config_service",
                        lambda: SimpleNamespace(get_all_servers=lambda: [{"a": 1}, {"b": 2}]))
    monkeypatch.setattr(web_routes.auth, "login_required", lambda f: f)
    # The caller is whoever the test says: both ways in are asked, so both are
    # stubbed here rather than one of them being quietly true.
    monkeypatch.setattr(web_routes, "session_user", lambda: None)
    monkeypatch.setattr(web_routes, "verify_password",
                        lambda user, password: "admin" if password == "admin" else None)
    application = Flask(__name__)
    application.config.update(TESTING=True, SECRET_KEY="health")
    web_routes.register_routes(application)
    return application


def test_the_public_answer_says_the_service_is_up(app):
    body = app.test_client().get("/health").get_json()

    assert body["status"] == "healthy"
    for field in PUBLIC:
        assert field in body, field


def test_the_public_answer_describes_no_installation(app):
    """THE FINDING. Each of these tells a stranger something about the machine
    and none of them tells anybody whether the service is healthy."""
    body = app.test_client().get("/health").get_json()
    leaked = [field for field in PRIVATE if field in body]

    assert leaked == [], (
        f"an unauthenticated caller is told {leaked} about this installation")


def test_no_version_string_slips_through_under_another_name(app):
    """Read as text, not by field name: moving the same value into a differently
    named field would pass the check above and leak exactly as much."""
    text = app.test_client().get("/health").get_data(as_text=True)

    assert "9.9.9" not in text, f"the version is in the public body: {text}"


def test_a_logged_in_caller_still_gets_everything(app):
    """Counter-check: the detail is moved, not deleted. An operator diagnosing
    a container by hand adds -u and has it back."""
    body = app.test_client().get("/health", headers=AUTH).get_json()

    for field in PUBLIC + PRIVATE:
        assert field in body, field
    assert body["version"] == "v9.9.9"
    assert body["servers_configured"] == 2


def test_a_session_login_counts_too(app, monkeypatch):
    """The panel logs in with a session cookie, not with Basic auth."""
    monkeypatch.setattr(web_routes, "session_user", lambda: "admin")
    body = app.test_client().get("/health").get_json()

    assert body["servers_configured"] == 2


def test_a_fresh_install_still_says_so_in_public(app, monkeypatch):
    """Not a disclosure: with no password set, the setup page is open to
    anybody who loads the panel, which is what a first run is."""
    monkeypatch.setattr(web_routes, "load_config",
                        lambda: {"web_ui_password_hash": None})
    body = app.test_client().get("/health").get_json()

    assert body["first_time_setup_needed"] is True
    assert body["setup_url"] == "/setup"


def test_a_configured_panel_does_not_announce_its_state(app):
    body = app.test_client().get("/health").get_json()

    assert "first_time_setup_needed" not in body
    assert "setup_url" not in body


def test_the_container_probe_reads_no_field(app):
    """The reason the body may shrink at all. The HEALTHCHECK opens the URL and
    checks that it does not raise; if it ever started reading a field, this
    test is where that shows up."""
    dockerfile = (web_routes.__file__.rsplit("/app/", 1)[0] + "/Dockerfile")
    with open(dockerfile, encoding="utf-8") as handle:
        probe = [line for line in handle if "/health" in line and "CMD" in line]

    assert probe, "the container has no health probe any more"
    for field in PRIVATE:
        assert field not in probe[0], f"the probe reads {field} out of the body"


def test_a_broken_configuration_is_still_healthy_in_public(app, monkeypatch):
    """Counter-check on the error path: a config that cannot be read must not
    turn the public answer into a description of the failure."""
    def explode():
        raise OSError("cannot read")

    monkeypatch.setattr(web_routes, "load_config", explode)
    response = app.test_client().get("/health")
    body = response.get_json()

    assert response.status_code == 200
    assert body["status"] == "healthy"
    assert "config_loaded" not in body
    assert json.dumps(body).find("cannot read") == -1, "the reason is public"

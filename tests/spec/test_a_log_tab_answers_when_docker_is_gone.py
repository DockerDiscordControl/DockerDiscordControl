# -*- coding: utf-8 -*-
"""
THE FINDING (review E46): C18 taught `_get_container_logs_sync` to say what
really went wrong - a `ContainerLogError` instead of a None that the caller read
as "no such container". It then taught the one caller it had in view,
`get_container_logs`, to answer that exception with a 500 that names it.

The other caller was left out, and it is the one the web panel actually uses.
The Bot, Discord, Web UI and Application tabs all go

    get_filtered_logs -> _get_bot_logs -> _get_filtered_container_logs
                      -> _get_container_logs_sync

and not one of those four handlers catches `ContainerLogError`:

    _get_filtered_container_logs   except (AttributeError, TypeError,
                                           RuntimeError, ValueError)
    get_filtered_logs              except (AttributeError, TypeError,
                                           ValueError, RuntimeError)
    the four routes                except (ImportError, AttributeError,
                                           RuntimeError) / (ValueError,
                                           TypeError, KeyError)

So when the log files are not there and Docker is unreachable - the moment the
operator opens a log tab to find out why - the exception walks out of the
service, out of the route, and Flask answers with its own HTML error page. The
log pane fills with markup instead of the one sentence that would have said
"Docker could not be reached".

`_get_filtered_container_logs` is declared `-> LogResult` and already answers
its sibling failure that way (`LogResult(..., status_code=404)` for a container
that is not there). The read failure now answers next to it, with a 500 that
names what happened, exactly as `get_container_logs` does.
"""

import sys
import types

import pytest

from services.web.container_log_service import (
    ContainerLogService,
    FilteredLogRequest,
    LogType,
)


class _NotFound(Exception):
    pass


class _APIError(Exception):
    pass


def _install_fake_docker(monkeypatch, failure):
    """A docker module whose containers.get raises `failure`."""

    class _Client:
        def __init__(self):
            self.containers = types.SimpleNamespace(get=self._get)

        @staticmethod
        def _get(name):
            raise failure

        def close(self):
            pass

    module = types.ModuleType("docker")
    module.errors = types.SimpleNamespace(NotFound=_NotFound, APIError=_APIError)
    module.DockerClient = lambda **kwargs: _Client()
    # The client comes from the factory since v3.0; hand it the fake's client.
    # Patched BEFORE the fake module goes in: importing the factory imports the
    # real docker package.
    # Without this the failure cases here stayed green for the wrong reason -
    # the real factory finds no Docker in the test container and fails too.
    monkeypatch.setattr(
        "services.docker_service.client_factory.build_docker_client",
        lambda **kwargs: module.DockerClient(**kwargs),
    )
    monkeypatch.setitem(sys.modules, "docker", module)


@pytest.fixture
def service(monkeypatch):
    """A service whose log files are all missing, so every tab falls through
    to the container logs - which is the situation the finding is about."""
    svc = ContainerLogService()
    svc.log_paths = {key: ["/nonexistent/ddc-test.log"] for key in svc.log_paths}
    return svc


# The four tabs that fall through to the container logs. CONTAINER and ACTION
# are not reached through get_filtered_logs at all.
FALLING_THROUGH = [LogType.BOT, LogType.DISCORD, LogType.WEBUI, LogType.APPLICATION]


@pytest.mark.parametrize("log_type", FALLING_THROUGH, ids=lambda t: t.value)
def test_every_log_tab_answers_when_docker_is_unreachable(service, monkeypatch, log_type):
    """THE FINDING: the operator opens a log tab, Docker is gone, and the tab
    has to say so rather than raise into Flask."""
    _install_fake_docker(monkeypatch, OSError("socket not available"))

    result = service.get_filtered_logs(FilteredLogRequest(log_type=log_type))

    assert result.success is False
    assert result.status_code == 500, result.error
    assert result.error, "the failure has to carry a sentence, not an empty string"
    assert "not found" not in result.error.lower(), (
        "an unreachable Docker is not a missing container (review C18)"
    )


@pytest.mark.parametrize(
    "route", ["/bot_logs", "/discord_logs", "/webui_logs", "/application_logs"]
)
def test_the_log_route_answers_plain_text_when_docker_is_unreachable(monkeypatch, route):
    """The whole way out. The web panel asks the route for a log tab, Docker is
    gone, and what comes back is a plain-text sentence with a status code - not
    Flask's HTML error page, and not a dead fetch."""
    from flask import Flask

    import app.auth as auth_module
    import services.web.container_log_service as module

    _install_fake_docker(monkeypatch, OSError("socket not available"))

    svc = ContainerLogService()
    svc.log_paths = {key: ["/nonexistent/ddc-test.log"] for key in svc.log_paths}
    monkeypatch.setattr(module, "get_container_log_service", lambda: svc)
    monkeypatch.setattr(auth_module.auth, "authenticate", lambda *a, **k: "admin")

    from app.blueprints.log_routes import log_bp

    flask_app = Flask(__name__)
    flask_app.register_blueprint(log_bp)

    response = flask_app.test_client().get(route)

    assert response.status_code == 500
    assert response.mimetype == "text/plain", (
        "an HTML error page is what the operator sees when the exception escapes"
    )
    assert response.get_data(as_text=True).strip()


def test_a_missing_container_is_still_a_404(service, monkeypatch):
    """COUNTER-CHECK: the meaning that was right stays right."""
    _install_fake_docker(monkeypatch, _NotFound("no such container"))

    result = service.get_filtered_logs(FilteredLogRequest(log_type=LogType.BOT))

    assert result.success is False
    assert result.status_code == 404
    assert "not found" in (result.error or "").lower()

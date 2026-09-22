# -*- coding: utf-8 -*-
"""
THE FINDING (review C18, section 29 F3): `_get_container_logs_sync` ends with

    except Exception as e:
        self.logger.error(...)
        return None

and its caller reads that None as one thing only:

    if logs_content is None:
        return LogResult(success=False,
                         error=f"Container '{...}' not found", status_code=404)

So a Docker socket that is unreachable, a permission denied, a timeout - every
failure that has nothing to do with the container - is reported to whoever is
troubleshooting the log viewer as "this container does not exist". The person
who most needs to know that Docker is unreachable is told the opposite, with a
404 to match.

None keeps its one meaning - the container is genuinely not there. Everything
else becomes a ContainerLogError and arrives as a 500 that says what happened.

The counter-check (test_a_missing_container_is_still_a_404) holds the meaning
that was right all along.
"""

import sys
import types

import pytest

from services.exceptions import ContainerLogError
from services.web.container_log_service import ContainerLogRequest, ContainerLogService


class _NotFound(Exception):
    pass


class _APIError(Exception):
    pass


def _install_fake_docker(monkeypatch, failure):
    """A docker module whose containers.get raises `failure`."""
    closed = []

    class _Client:
        def __init__(self):
            self.containers = types.SimpleNamespace(get=self._get)

        @staticmethod
        def _get(name):
            raise failure

        def close(self):
            closed.append(True)

    module = types.ModuleType("docker")
    module.errors = types.SimpleNamespace(NotFound=_NotFound, APIError=_APIError)
    module.DockerClient = lambda **kwargs: _Client()
    # The client comes from the factory since v3.0; hand it the fake's client.
    # Patched BEFORE the fake module goes in: importing the factory imports the
    # real docker package.
    monkeypatch.setattr(
        "services.docker_service.client_factory.build_docker_client",
        lambda **kwargs: module.DockerClient(**kwargs),
    )
    monkeypatch.setitem(sys.modules, "docker", module)
    return closed


@pytest.fixture
def service():
    return ContainerLogService()


def test_an_unreachable_docker_is_not_a_missing_container(service, monkeypatch):
    """THE FINDING: the socket is gone, the container is not."""
    _install_fake_docker(monkeypatch, OSError("socket not available"))

    result = service.get_container_logs(ContainerLogRequest(container_name="web"))

    assert result.success is False
    assert result.status_code == 500, result.error
    assert "not found" not in (result.error or "").lower()


def test_a_docker_api_error_is_not_a_missing_container(service, monkeypatch):
    """A Docker API error is a Docker problem, not a missing container."""
    _install_fake_docker(monkeypatch, _APIError("daemon says no"))

    with pytest.raises(ContainerLogError):
        service._get_container_logs_sync("web", 100)


def test_the_client_is_closed_even_when_it_fails(service, monkeypatch):
    """Whatever happens, the Docker client is released."""
    closed = _install_fake_docker(monkeypatch, OSError("socket not available"))

    service.get_container_logs(ContainerLogRequest(container_name="web"))

    assert closed == [True]


def test_a_missing_container_is_still_a_404(service, monkeypatch):
    """COUNTER-CHECK: the meaning that was right stays right."""
    _install_fake_docker(monkeypatch, _NotFound("no such container"))

    result = service.get_container_logs(ContainerLogRequest(container_name="ghost"))

    assert result.success is False
    assert result.status_code == 404
    assert "not found" in (result.error or "").lower()

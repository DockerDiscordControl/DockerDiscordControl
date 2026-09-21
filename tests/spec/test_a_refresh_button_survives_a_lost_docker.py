# -*- coding: utf-8 -*-
"""One container's status fetch must fail as a status, not as an exception.

THE FINDING (review E16, the last open DDC-exception scan hit):
``StatusHandlersMixin.get_status`` is the SINGLE-container path - what the
refresh button on a container panel calls (``control_ui.py:478``, ``:557``,
``:2208``) and what ``docker_control.py:1065`` calls. Its whole job is to come
back with a ``ContainerStatusResult``, including
``ContainerStatusResult.error_result`` when the fetch does not work, so the
panel can show the failure in place.

Its handler listed ``(RuntimeError, OSError, ValueError, KeyError, TypeError)``.
The chain underneath it, read out of the code by
``scripts/review/scan_handlers.py``:

    get_docker_info_dict_service_first
      -> get_container_status
        -> _fetch_container_status
          -> get_docker_client_async        raises DockerConnectionError

``DockerConnectionError`` is in none of those five, so when the Docker daemon
is gone the refresh button raised instead of showing a failed container.

The bulk path is not affected - ``bulk_fetch_container_status`` asks
``check_connectivity`` first, and review B25 turns an exception in a gathered
result into a named error result. This path has neither: no pre-check, and
nothing above it that turns an exception back into a result. That is why the
same sentence had to be answered twice.
"""

import pytest

from services.exceptions import DockerConnectionError


@pytest.fixture
def docker_is_gone(monkeypatch):
    import cogs.status_handlers as status_handlers

    async def raises(*_a, **_kw):
        raise DockerConnectionError("Failed to create Docker client: connection refused")

    monkeypatch.setattr(status_handlers, "get_docker_info_dict_service_first", raises)


def _handlers():
    from cogs.status_handlers import StatusHandlersMixin
    return StatusHandlersMixin.__new__(StatusHandlersMixin)


@pytest.mark.asyncio
async def test_the_button_gets_a_result_not_an_exception(docker_is_gone):
    from cogs.status_handlers import StatusHandlersMixin

    result = await StatusHandlersMixin.get_status(
        _handlers(), {"docker_name": "alpha", "display_name": "Alpha"})

    assert result is not None, "the refresh button raised instead of answering"


@pytest.mark.asyncio
async def test_the_result_names_the_container_that_failed(docker_is_gone):
    from cogs.status_handlers import StatusHandlersMixin

    result = await StatusHandlersMixin.get_status(
        _handlers(), {"docker_name": "alpha", "display_name": "Alpha"})

    assert result.docker_name == "alpha"
    assert getattr(result, "error", None) is not None, (
        "the failure was answered, but with nothing saying what went wrong"
    )

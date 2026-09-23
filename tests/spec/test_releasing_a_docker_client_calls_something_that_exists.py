# -*- coding: utf-8 -*-
"""Releasing a Docker client calls a method that exists.

THE FINDING (independent review of the Docker layer, 2026-09-23), and it is two
faults stacked:

    # docker_utils.release_docker_client
    pool = get_docker_client_service()
    pool._release_client(client)          # the service has no such method
    ...
    except (AttributeError, RuntimeError, ValueError) as e:
        logger.debug(f"Error releasing client to pool: {e}")   # DEBUG

DockerClientService defines `_release_client_async` and nothing called
`_release_client`. So the call raises AttributeError every time, the handler
swallows it at DEBUG level, and the release silently does nothing.

AND THE TEST THAT WAS SUPPOSED TO CATCH IT CANNOT:

    fake_pool = MagicMock()
    ...
    fake_pool._release_client.assert_called_once_with(client)

A MagicMock invents any attribute it is asked for, so the assertion passes on a
method that does not exist. It is green, it names the right thing, and it can
never fail on it - the exact shape the quality rules call out as the most
common and most treacherous mistake.

WHAT THIS TEST DOES INSTEAD: it asks the REAL class. A name that is not there
is red, whatever a mock would have said.

WHAT THE CODE DOES INSTEAD: there is no synchronous release - the only one is
`_release_client_async`, and this function is sync, so it could never have
worked. In pool mode it now CLOSES the client, which is synchronous, correct,
and exactly what the live path (get_docker_client_async) already does in its
finally block.

STILL TO DECIDE, and reported rather than decided here: release_docker_client
has no production caller at all, and neither does its sibling
get_docker_client. They are reached only from tests. Whether to remove them is
the operator's call; this makes them honest in the meantime.

COUNTER-CHECK (2026-09-23): red before - `_release_client` is not on the class.
The other tests keep the function's own job: a client is released, and the
legacy branch still works.
"""

from unittest.mock import MagicMock, patch

import pytest

from services.docker_service import docker_utils
from services.docker_service.docker_client_pool import DockerClientService


def test_every_method_it_calls_is_on_the_real_class():
    """THE FINDING: it called one that is not, and a MagicMock said yes."""
    import inspect
    import re

    source = inspect.getsource(docker_utils.release_docker_client)
    called = set(re.findall(r"\bpool\.(\w+)\s*\(", source))

    missing = sorted(name for name in called if not hasattr(DockerClientService, name))
    assert missing == [], (
        f"release_docker_client calls {missing} on DockerClientService, which "
        "has no such method - the AttributeError is swallowed at DEBUG and the "
        "release silently does nothing")


def test_the_client_is_actually_released(monkeypatch):
    """Whatever it calls, the client must not simply be dropped."""
    monkeypatch.setattr(docker_utils, "USE_CONNECTION_POOL", True)
    client = MagicMock()

    with patch.object(docker_utils, "get_docker_client_service",
                      return_value=MagicMock()):
        docker_utils.release_docker_client(client=client)

    assert client.close.called, (
        "the client was neither returned to the pool nor closed - its socket "
        "lives until the garbage collector gets to it")


def test_a_client_that_cannot_be_closed_is_not_an_error(monkeypatch):
    """Counter-check: releasing must never raise at its caller."""
    monkeypatch.setattr(docker_utils, "USE_CONNECTION_POOL", True)
    client = MagicMock()
    client.close.side_effect = OSError("socket already gone")

    with patch.object(docker_utils, "get_docker_client_service",
                      return_value=MagicMock()):
        docker_utils.release_docker_client(client=client)   # must not raise


def test_without_the_pool_nothing_changes(monkeypatch):
    """Counter-check: the legacy branch is untouched."""
    monkeypatch.setattr(docker_utils, "USE_CONNECTION_POOL", False)

    docker_utils.release_docker_client()   # must not raise


def test_the_real_release_is_async_and_still_there():
    """The one that does work, so this file cannot pass by deleting both."""
    assert hasattr(DockerClientService, "_release_client_async")

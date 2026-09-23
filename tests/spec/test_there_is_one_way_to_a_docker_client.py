# -*- coding: utf-8 -*-
"""docker_utils has one way to a Docker client, and it is the async one.

THIS FILE REPLACES test_releasing_a_docker_client_calls_something_that_exists.py,
whose job is done. That test found `release_docker_client` calling
`pool._release_client(client)` - a method DockerClientService does not have, so
the call raised AttributeError, the handler swallowed it at DEBUG, and the
release silently did nothing. It also found the test that was supposed to catch
that asserting on a MagicMock, which invents any attribute it is asked for and
can therefore never fail. Both were fixed on 2026-09-23, and the file ended
with the open question it could not answer itself:

    STILL TO DECIDE ... release_docker_client has no production caller at all,
    and neither does its sibling get_docker_client. Whether to remove them is
    the operator's call.

OPERATOR DECISION (2026-09-23): remove them.

WHY IT IS WORTH A TEST AND NOT JUST A DELETE: `get_docker_client()` was a
SECOND, SYNCHRONOUS way to a Docker client, and it cached one for five minutes
in a module global. v3.0 spends its effort on there being one way to the
socket, through the client factory and the allowlist proxy
(docs/V3_ARCHITECTURE_PLAN.md §6, and
tests/spec/test_every_docker_client_site_is_known.py). A second door with a
long-lived client behind it is the kind of thing that gets used again the
moment somebody needs a client outside async code, and then it is not dead any
more. This says it stays shut.

HOW THIS TEST CAN FAIL: it asks the module for the names. Adding a synchronous
getter back, under either name, is red. So is losing the async one.

COUNTER-CHECK (2026-09-23): red before - both functions were still there, with
their three module globals.
"""

import inspect

from services.docker_service import docker_utils
from services.docker_service.docker_client_pool import DockerClientService


def test_there_is_no_synchronous_client_getter():
    """THE POINT: one way in, and it is the async one."""
    assert not hasattr(docker_utils, "get_docker_client"), (
        "a synchronous Docker client getter is back - it bypasses the pool and "
        "keeps a client alive outside anyone's control")
    assert not hasattr(docker_utils, "release_docker_client")


def test_the_cached_client_globals_are_gone_too():
    """Counter-check: deleting the functions and leaving the state they held
    would be half a delete, and the next reader would wire them up again."""
    for name in ("_docker_client", "_client_last_used", "_CLIENT_TIMEOUT",
                 "_client_ping_cache", "_PING_CACHE_TTL", "_docker_client_lock"):
        assert not hasattr(docker_utils, name), f"{name} outlived its only users"


def test_the_async_way_is_still_there():
    """So this file cannot be passed by deleting everything."""
    assert hasattr(docker_utils, "get_docker_client_async")
    assert hasattr(DockerClientService, "_release_client_async"), (
        "the real release - the one the async path uses in its finally block")


def test_the_pool_switch_stays():
    """USE_CONNECTION_POOL is NOT part of this: scripts/monitor_docker_queue.py
    reads it, and get_docker_client_async branches on it."""
    assert hasattr(docker_utils, "USE_CONNECTION_POOL")
    assert "USE_CONNECTION_POOL" in inspect.getsource(docker_utils.get_docker_client_async)
